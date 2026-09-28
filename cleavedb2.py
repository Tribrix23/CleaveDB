#!/usr/bin/env python3
"""
CLEAVEDB 2 - fast ingest + fast queries + *soft* relationships.  (SQLite only; optional orjson.)

THE MIDDLE GROUND
  Relational: relationships are declared, typed, directional, indexed BOTH ways, and can be
              joined, traversed, restricted or cascaded.
  Document:   everything else is schemaless JSON, and a relationship may point at a record
              that does not exist yet (LATE BINDING - the link snaps on when the target arrives).
  You choose per relationship:  strict=True (target must exist)  or  soft (default).
                                on_delete = "keep" | "restrict" | "cascade".

HOW IT IS FAST
  * ids are 63-bit hashes of "collection/id": stateless routing across shards, and links can be
    stored before their target exists.
  * batched writes (put_many / ingest), WAL, one transaction per shard, sorted bulk inserts,
    updates write only the DIFF of index rows.
  * numeric fields -> range index (+ probe index), text -> FTS5/BM25, edges -> two indexes
    (out and in), all facets derived from the document (the document is the truth).
  * a small planner picks the most selective driver (text / a numeric range / a graph
    neighbourhood / newest-first scan) and turns the rest into cheap probes; top-k is pushed
    down to SQL; shards are queried in parallel and merged.

LIMITS (honest)
  Single machine.  Atomic per shard; cross-shard edge indexes are eventually consistent and
  repaired by heal().  Shard count is fixed at creation.  After relate()/index() on existing
  data, run heal().  Hash collisions are detected on write (63-bit).  Needs SQLite with FTS5
  for text search (everything else works without it).

API
  db = CleaveDB(path_or_":memory:", shards=1)
  db.relate("orders", "customer", "customers", strict=False, on_delete="keep", many=False)
  db.index("orders", "total", "qty")                 # index only these numeric fields (faster writes)
  db.put(coll, id, doc, ts=None) | put_many(coll, [(id, doc[, ts]), ...]) | ingest(coll, id, doc)
  db.get(coll, id) | delete(coll, id) | expire(coll, before)
  db.find(coll, text=, where=[("total",">=",100)], near="customers/c1", depth=1, since=, until=,
          limit=20, order="score"|"ts"|"oldest", join=["customer"])
  db.query('in:orders espresso total>=100 since:2026-01-01 near:customers/c1 limit:5')
  db.count(...) | agg(coll, field, ...) | follow(coll, id, rel, depth, direction) | dangling() | heal()
"""
import collections, contextlib, datetime, hashlib, itertools, json, os, random, re
import sqlite3, sys, threading, time, types
from concurrent.futures import ThreadPoolExecutor

try:
    import orjson
    _dumps, _loads = orjson.dumps, orjson.loads
except ImportError:
    def _dumps(o): return json.dumps(o, separators=(",", ":")).encode()
    _loads = json.loads

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(gid INTEGER PRIMARY KEY, key TEXT NOT NULL, coll TEXT NOT NULL, ts REAL NOT NULL, body BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS docs_ct ON docs(coll, ts);
CREATE TABLE IF NOT EXISTS nums(field TEXT NOT NULL, val REAL NOT NULL, gid INTEGER NOT NULL, PRIMARY KEY(field, val, gid)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS nums_g ON nums(gid, field, val);
CREATE TABLE IF NOT EXISTS eout(src INTEGER NOT NULL, rel INTEGER NOT NULL, dst INTEGER NOT NULL, PRIMARY KEY(src, rel, dst)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ein(dst INTEGER NOT NULL, rel INTEGER NOT NULL, src INTEGER NOT NULL, PRIMARY KEY(dst, rel, src)) WITHOUT ROWID;
"""
META = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS rels(id INTEGER PRIMARY KEY, name TEXT UNIQUE, src TEXT, field TEXT, dst TEXT, strict INTEGER, on_delete TEXT, many INTEGER);
CREATE TABLE IF NOT EXISTS idx(coll TEXT PRIMARY KEY, fields TEXT);
"""
_MASK = (1 << 63) - 1
_OPS = {">", ">=", "<", "<=", "=", "!="}
_PRED = re.compile(r"^([A-Za-z_][\w.]*)(>=|<=|!=|>|<|=)(-?\d+(?:\.\d+)?)$")
_WORD = re.compile(r"\w+\*?")
Rel = collections.namedtuple("Rel", "id name src field dst strict on_delete many")
Prep = collections.namedtuple("Prep", "gid key coll ts body text nums edges")

class IntegrityError(Exception): pass
class KeyCollision(Exception): pass

def gid_of(key):
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big") & _MASK

def chunks(seq, n=500):
    for i in range(0, len(seq), n): yield seq[i:i + n]

def to_ts(x):
    if isinstance(x, (int, float)): return float(x)
    if isinstance(x, datetime.datetime): return x.timestamp()
    if isinstance(x, datetime.date): return datetime.datetime(x.year, x.month, x.day).timestamp()
    return datetime.datetime.fromisoformat(x).timestamp()

class CleaveDB:
    def __init__(self, path=":memory:", shards=1, durable=False, batch=5000, cap=2000):
        self.n, self.batch, self.cap = shards, batch, cap
        self.mem = path == ":memory:"
        if not self.mem: os.makedirs(path, exist_ok=True)
        self.locks = [threading.RLock() for _ in range(shards)]
        self.conns, self.has_fts = [], True
        for s in range(shards):
            f = ":memory:" if self.mem else os.path.join(path, f"shard{s}.db")
            c = sqlite3.connect(f, check_same_thread=False, isolation_level=None)
            for p in ("journal_mode=WAL", "synchronous=" + ("FULL" if durable else "NORMAL"),
                      "temp_store=MEMORY", "cache_size=-262144", "mmap_size=268435456"):
                c.execute("PRAGMA " + p)
            c.executescript(SCHEMA)
            try: c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(t, tokenize='porter unicode61')")
            except sqlite3.OperationalError: self.has_fts = False
            self.conns.append(c)
        c0 = self.conns[0]
        c0.executescript(META)
        row = c0.execute("SELECT v FROM meta WHERE k='shards'").fetchone()
        if row and int(row[0]) != shards:
            raise ValueError(f"database was created with shards={row[0]}; shard count is fixed")
        c0.execute("INSERT OR IGNORE INTO meta VALUES('shards', ?)", (str(shards),))
        self.rels, self.rel_by_id, self.refs, self.idx = {}, {}, collections.defaultdict(dict), {}
        for r in c0.execute("SELECT id,name,src,field,dst,strict,on_delete,many FROM rels"):
            self._reg(Rel(r[0], r[1], r[2], r[3], r[4], bool(r[5]), r[6], bool(r[7])))
        for coll, fields in c0.execute("SELECT coll, fields FROM idx"): self.idx[coll] = set(json.loads(fields))
        self.pool = ThreadPoolExecutor(shards) if shards > 1 else None
        self._buf, self._blk = [], threading.Lock()

    # ------------------------------------------------------------- plumbing
    def _reg(self, r):
        self.rels[r.name] = r; self.rel_by_id[r.id] = r; self.refs[r.src][r.field] = r

    def _by_shard(self, gids):
        d = collections.defaultdict(list)
        for g in gids: d[g % self.n].append(g)
        return d

    def _group(self, rows):
        d = collections.defaultdict(list)
        for r in rows: d[r[0] % self.n].append(r)
        return d

    def _scatter(self, fn, shards=None):
        shards = list(range(self.n) if shards is None else shards)
        if self.pool is None or len(shards) < 2: return [fn(s) for s in shards]
        return list(self.pool.map(fn, shards))

    @contextlib.contextmanager
    def _tx(self, s):
        with self.locks[s]:
            c = self.conns[s]
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                try: c.execute("ROLLBACK")
                except sqlite3.OperationalError: pass
                raise

    def close(self):
        self.flush()
        for c in self.conns: c.close()
        if self.pool: self.pool.shutdown()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    # ---------------------------------------------------------- declarations
    def relate(self, src, field, dst, strict=False, on_delete="keep", many=False):
        """Declare src.field -> dst.  Existing data needs heal() to pick the relation up."""
        if on_delete not in ("keep", "restrict", "cascade"): raise ValueError("on_delete: keep|restrict|cascade")
        name = f"{src}.{field}"
        with self.locks[0]:
            c = self.conns[0]
            c.execute("INSERT INTO rels(name,src,field,dst,strict,on_delete,many) VALUES(?,?,?,?,?,?,?) "
                      "ON CONFLICT(name) DO UPDATE SET dst=excluded.dst, strict=excluded.strict, "
                      "on_delete=excluded.on_delete, many=excluded.many",
                      (name, src, field, dst, int(strict), on_delete, int(many)))
            rid = c.execute("SELECT id FROM rels WHERE name=?", (name,)).fetchone()[0]
        r = Rel(rid, name, src, field, dst, bool(strict), on_delete, bool(many))
        self._reg(r)
        return r

    def index(self, coll, *fields):
        """Index only these numeric fields for coll (none given = index all numeric fields)."""
        with self.locks[0]:
            if fields:
                self.conns[0].execute("INSERT OR REPLACE INTO idx VALUES(?,?)", (coll, json.dumps(sorted(fields))))
                self.idx[coll] = set(fields)
            else:
                self.conns[0].execute("DELETE FROM idx WHERE coll=?", (coll,)); self.idx.pop(coll, None)

    # ---------------------------------------------------------- cleave apart
    def _derive(self, coll, doc):
        refs, only = self.refs.get(coll, {}), self.idx.get(coll)
        texts, nums, edges, stack = [], set(), [], [("", doc)]
        while stack:
            path, v = stack.pop()
            t = type(v)
            if t is dict:
                for k, x in v.items(): stack.append((f"{path}.{k}" if path else k, x))
            elif t is list or t is tuple:
                for x in v: stack.append((path, x))
            elif t is str:
                r = refs.get(path)
                if r is not None: edges.append((r.id, v if v.startswith(r.dst + "/") else f"{r.dst}/{v}"))
                elif v[:1] == "@" and len(v) > 1: edges.append((0, v[1:]))
                else: texts.append(v)
            elif t is bool or t is int or t is float:
                r = refs.get(path)
                if r is not None: edges.append((r.id, f"{r.dst}/{v}"))
                elif (only is None or path in only) and v == v and abs(v) != float("inf"):
                    nums.add((f"{coll}.{path}", float(v)))
        return " ".join(texts), nums, edges

    # ----------------------------------------------------------------- write
    def put(self, coll, id_, doc, ts=None): return self.put_many(coll, [(id_, doc)], ts)

    def put_many(self, coll, items, ts=None):
        self.flush()
        return self._write(coll, items, ts)

    def ingest(self, coll, id_, doc, ts=None):
        """Buffered write for firehose ingest; flushed automatically (and before any read)."""
        with self._blk:
            self._buf.append((coll, id_, doc, ts))
            full = len(self._buf) >= self.batch
        if full: self.flush()

    def flush(self):
        with self._blk: buf, self._buf = self._buf, []
        for coll, grp in itertools.groupby(buf, key=lambda x: x[0]):
            self._write(coll, [(i, d, t) for _, i, d, t in grp])

    def _write(self, coll, items, ts):
        default_ts = time.time() if ts is None else to_ts(ts)
        prep, need = {}, {}
        for it in items:
            t = to_ts(it[2]) if len(it) > 2 and it[2] is not None else default_ts
            key = f"{coll}/{it[0]}"; g = gid_of(key)
            text, nums, edges = self._derive(coll, it[1])
            eset = set()
            for rel, dkey in edges:
                dg = gid_of(dkey); eset.add((rel, dg))
                if rel and self.rel_by_id[rel].strict: need[dg] = dkey
            prep[g] = Prep(g, key, coll, t, _dumps(it[1]), text, nums, eset)
        if not prep: return 0
        cand = [g for g in need if g not in prep]
        if cand:
            miss = [need[g] for g in set(cand) - self._exists(cand)]
            if miss: raise IntegrityError(f"strict relation: target(s) not found: {sorted(miss)[:5]}")
        by = collections.defaultdict(list)
        for p in prep.values(): by[p.gid % self.n].append(p)
        for lst in by.values(): lst.sort(key=lambda p: p.gid)
        res = self._scatter(lambda s: self._shard_write(s, by[s]), list(by))
        adds = [e for a, _ in res for e in a]; dels = [e for _, d in res for e in d]
        if adds or dels: self._apply_ein(adds, dels)
        return len(prep)

    def _shard_write(self, s, P):
        ein_add, ein_del = [], []
        with self._tx(s) as c:
            old = {}
            gids = [p.gid for p in P]
            for ch in chunks(gids):
                for g, k, cl, body in c.execute(
                        f"SELECT gid,key,coll,body FROM docs WHERE gid IN ({','.join('?' * len(ch))})", ch):
                    old[g] = (k, cl, body)
            rows, fts_add, nums_add, nums_del, eo_add, eo_del = [], [], [], [], [], []
            for p in P:
                rows.append((p.gid, p.key, p.coll, p.ts, p.body))
                if p.text: fts_add.append((p.gid, p.text))
                o = old.get(p.gid)
                if o:
                    if o[0] != p.key: raise KeyCollision(f"{p.key} collides with {o[0]}")
                    onums = self._derive(o[1], _loads(o[2]))[1]
                    oe = set(c.execute("SELECT rel,dst FROM eout WHERE src=?", (p.gid,)))
                    nums_del += [(f, v, p.gid) for f, v in onums - p.nums]
                    nums_add += [(f, v, p.gid) for f, v in p.nums - onums]
                else:
                    oe = set()
                    nums_add += [(f, v, p.gid) for f, v in p.nums]
                for r, d in oe - p.edges: eo_del.append((p.gid, r, d)); ein_del.append((d, r, p.gid))
                for r, d in p.edges - oe: eo_add.append((p.gid, r, d)); ein_add.append((d, r, p.gid))
            if old and self.has_fts: c.executemany("DELETE FROM fts WHERE rowid=?", [(g,) for g in old])
            c.executemany("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?)", rows)
            if fts_add: c.executemany("INSERT INTO fts(rowid,t) VALUES (?,?)", fts_add)
            if nums_del: c.executemany("DELETE FROM nums WHERE field=? AND val=? AND gid=?", nums_del)
            if nums_add: c.executemany("INSERT OR IGNORE INTO nums VALUES (?,?,?)", sorted(nums_add))
            if eo_del: c.executemany("DELETE FROM eout WHERE src=? AND rel=? AND dst=?", eo_del)
            if eo_add: c.executemany("INSERT OR IGNORE INTO eout VALUES (?,?,?)", sorted(eo_add))
            mine_d = [e for e in ein_del if e[0] % self.n == s]
            mine_a = [e for e in ein_add if e[0] % self.n == s]
            if mine_d: c.executemany("DELETE FROM ein WHERE dst=? AND rel=? AND src=?", mine_d)
            if mine_a: c.executemany("INSERT OR IGNORE INTO ein VALUES (?,?,?)", sorted(mine_a))
        return ([e for e in ein_add if e[0] % self.n != s], [e for e in ein_del if e[0] % self.n != s])

    def _apply_ein(self, adds, dels):
        A, D = self._group(adds), self._group(dels)
        def task(s):
            with self._tx(s) as c:
                if D.get(s): c.executemany("DELETE FROM ein WHERE dst=? AND rel=? AND src=?", D[s])
                if A.get(s): c.executemany("INSERT OR IGNORE INTO ein VALUES (?,?,?)", sorted(A[s]))
        self._scatter(task, sorted(set(A) | set(D)))

    # ------------------------------------------------------------ point ops
    def get(self, coll, id_):
        self.flush()
        key = f"{coll}/{id_}"; g = gid_of(key); s = g % self.n
        with self.locks[s]:
            r = self.conns[s].execute("SELECT body FROM docs WHERE gid=? AND key=?", (g, key)).fetchone()
        return _loads(r[0]) if r else None

    def _exists(self, gids):
        out = set()
        for s, lst in self._by_shard(gids).items():
            with self.locks[s]:
                for ch in chunks(lst):
                    out.update(r[0] for r in self.conns[s].execute(
                        f"SELECT gid FROM docs WHERE gid IN ({','.join('?' * len(ch))})", ch))
        return out

    def _fetch(self, gids, body=True):
        out = {}
        for s, lst in self._by_shard(gids).items():
            with self.locks[s]:
                for ch in chunks(lst):
                    for r in self.conns[s].execute(
                            f"SELECT gid,key{',body' if body else ''} FROM docs WHERE gid IN ({','.join('?' * len(ch))})", ch):
                        out[r[0]] = r[1:]
        return out

    # ---------------------------------------------------------------- delete
    def delete(self, coll, id_):
        """Delete one record, honouring on_delete rules (restrict raises, cascade follows)."""
        self.flush()
        g = gid_of(f"{coll}/{id_}")
        return self._delete_gids([g]) if g in self._exists([g]) else 0

    def expire(self, coll, before):
        """Retention: delete records of coll older than `before` (ISO date/time or epoch seconds)."""
        self.flush()
        t, total = to_ts(before), 0
        def task(s):
            with self.locks[s]:
                return [r[0] for r in self.conns[s].execute(
                    "SELECT gid FROM docs WHERE coll=? AND ts<? LIMIT 20000", (coll, t))]
        while True:
            gids = [g for part in self._scatter(task) for g in part]
            if not gids: return total
            k = self._delete_gids(gids)
            total += k
            if k == 0: return total

    def _incoming(self, gids):
        out = []
        for s, lst in self._by_shard(gids).items():
            with self.locks[s]:
                for ch in chunks(lst):
                    out += self.conns[s].execute(
                        f"SELECT dst,rel,src FROM ein WHERE dst IN ({','.join('?' * len(ch))})", ch).fetchall()
        return out

    def _delete_gids(self, gids):
        victims, queue, restrict = set(gids), list(gids), []
        while queue:
            batch, queue = queue, []
            for dst, rel, src in self._incoming(batch):
                r = self.rel_by_id.get(rel)
                if r is None: continue
                if r.on_delete == "cascade":
                    if src not in victims: victims.add(src); queue.append(src)
                elif r.on_delete == "restrict": restrict.append((src, dst, r.name))
        bad = [b for b in restrict if b[0] not in victims]
        if bad:
            live = self._exists({b[0] for b in bad})
            bad = [b for b in bad if b[0] in live]
            if bad:
                k = self._fetch([bad[0][0], bad[0][1]], body=False)
                raise IntegrityError(f"cannot delete {k[bad[0][1]][0]}: referenced by {k[bad[0][0]][0]} via {bad[0][2]}")
        return self._remove(victims)

    def _remove(self, gids):
        by = self._by_shard(gids)
        def task(s):
            n, dels = 0, []
            with self._tx(s) as c:
                for ch in chunks(by[s]):
                    rows = c.execute(f"SELECT gid,coll,body FROM docs WHERE gid IN ({','.join('?' * len(ch))})", ch).fetchall()
                    if not rows: continue
                    present = [r[0] for r in rows]; pq = ",".join("?" * len(present))
                    if self.has_fts: c.executemany("DELETE FROM fts WHERE rowid=?", [(g,) for g in present])
                    c.executemany("DELETE FROM nums WHERE field=? AND val=? AND gid=?",
                                  [(f, v, g) for g, cl, b in rows for f, v in self._derive(cl, _loads(b))[1]])
                    dels += [(d, r, sr) for sr, r, d in c.execute(f"SELECT src,rel,dst FROM eout WHERE src IN ({pq})", present)]
                    c.execute(f"DELETE FROM eout WHERE src IN ({pq})", present)
                    c.execute(f"DELETE FROM docs WHERE gid IN ({pq})", present)
                    n += len(present)
                mine = [e for e in dels if e[0] % self.n == s]
                if mine: c.executemany("DELETE FROM ein WHERE dst=? AND rel=? AND src=?", mine)
            return n, [e for e in dels if e[0] % self.n != s]
        res = self._scatter(task, list(by))
        others = [e for _, o in res for e in o]
        if others: self._apply_ein([], others)
        return sum(n for n, _ in res)

    # ----------------------------------------------------------------- graph
    def _rel_id(self, coll, rel, direction):
        if rel is None: return None
        if rel == "@": return 0
        if "." in rel: return self.rels[rel].id
        if direction != "out": raise ValueError("incoming traversal needs the full relation name, e.g. 'orders.customer'")
        return self.rels[f"{coll}.{rel}"].id

    def _bfs(self, start, depth, direction, rid, cap=200000):
        seen, frontier = {start: 0}, [start]
        extra = [] if rid is None else [rid]
        rr = "" if rid is None else " AND rel=?"
        for h in range(1, depth + 1):
            nxt = set()
            for s, lst in self._by_shard(frontier).items():
                with self.locks[s]:
                    c = self.conns[s]
                    for ch in chunks(lst):
                        q = ",".join("?" * len(ch))
                        if direction in ("out", "both"):
                            nxt.update(r[0] for r in c.execute(f"SELECT dst FROM eout WHERE src IN ({q}){rr}", ch + extra))
                        if direction in ("in", "both"):
                            nxt.update(r[0] for r in c.execute(f"SELECT src FROM ein WHERE dst IN ({q}){rr}", ch + extra))
            frontier = [g for g in nxt if g not in seen]
            for g in frontier: seen[g] = h
            if not frontier or len(seen) > cap: break
        del seen[start]
        return seen

    def follow(self, coll, id_, rel=None, depth=1, direction="out", limit=1000, docs=True):
        """Traverse relationships. direction: out | in | both. Only records that exist are returned."""
        self.flush()
        hops = self._bfs(gid_of(f"{coll}/{id_}"), depth, direction, self._rel_id(coll, rel, direction))
        got = self._fetch(list(hops), body=docs)
        rows = [{"key": v[0], "hop": hops[g], **({"doc": _loads(v[1])} if docs else {})} for g, v in got.items()]
        rows.sort(key=lambda r: (r["hop"], r["key"]))
        return rows[:limit]

    def dangling(self, rel=None, limit=100):
        """Soft-integrity report: links whose target record does not exist (yet)."""
        self.flush()
        rid = None if rel is None else self._rel_id(None, rel, "in" if "." in rel or rel == "@" else "out")
        found = []
        for s in range(self.n):
            last = (-1, -1, -1)
            while len(found) < limit:
                with self.locks[s]:
                    rows = self.conns[s].execute(
                        "SELECT src,rel,dst FROM eout WHERE (src,rel,dst) > (?,?,?)"
                        + ("" if rid is None else f" AND rel={int(rid)}") + " ORDER BY src,rel,dst LIMIT 20000", last).fetchall()
                if not rows: break
                last = rows[-1]
                live = self._exists({r[2] for r in rows})
                found += [r for r in rows if r[2] not in live]
        found = found[:limit]
        docs = self._fetch({r[0] for r in found})
        out = []
        for src, rl, dst in found:
            if src not in docs: continue
            key, body = docs[src]
            _, _, edges = self._derive(key.split("/", 1)[0], _loads(body))
            miss = next((k for r, k in edges if r == rl and gid_of(k) == dst), "?")
            out.append({"from": key, "relation": self.rel_by_id[rl].name if rl else "@", "missing": miss})
        return out

    # ----------------------------------------------------------------- query
    def _match(self, text):
        ws = _WORD.findall(text.lower())
        return " ".join(f'"{w[:-1]}"*' if w.endswith("*") and len(w) > 1 else f'"{w.rstrip("*")}"' for w in ws) or None

    def _q(self, coll, text, where, near, depth, since, until):
        if where and not coll: raise ValueError("where= needs coll=")
        for _, op, _ in where:
            if op not in _OPS: raise ValueError(f"bad operator {op!r}")
        q = types.SimpleNamespace(coll=coll, where=list(where), match=None, nb=None, order="ts", limit=20,
                                  since=None if since is None else to_ts(since),
                                  until=None if until is None else to_ts(until))
        if text:
            if not self.has_fts: raise RuntimeError("this SQLite build has no FTS5: text search unavailable")
            q.match = self._match(text)
        if near is not None:
            key = near if isinstance(near, str) else "/".join(map(str, near))
            hops = self._bfs(gid_of(key), depth, "both", None)
            if not hops: return None
            q.nb = self._by_shard(hops)
        return q

    def _est(self, q, kind, arg):
        with self.locks[0]:
            c = self.conns[0]
            if kind == "text":
                return c.execute("SELECT COUNT(*) FROM (SELECT 1 FROM fts WHERE fts MATCH ? LIMIT ?)", (q.match, self.cap)).fetchone()[0]
            f, op, v = arg
            return c.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM nums WHERE field=? AND val{op}? LIMIT ?)",
                             (f"{q.coll}.{f}", float(v), self.cap)).fetchone()[0]

    def _plan(self, q):
        """Pick the most selective driver; everything else becomes a cheap probe."""
        if q.nb is not None: return ("near", None)
        if q.match and q.order == "score": return ("text", None)
        best = None
        for kind, arg in ([("text", None)] if q.match else []) + [("num", p) for p in q.where]:
            e = self._est(q, kind, arg)
            if e < self.cap and (best is None or e < best[0]): best = (e, kind, arg)
        if best: return best[1], best[2]
        return ("text", None) if q.match else ("scan", None)

    def _run(self, s, q, plan, mode, field=None):
        kind, arg = plan
        empty = {"rows": [], "count": 0, "agg": (0, None, None, None)}[mode]
        with self.locks[s]:
            c = self.conns[s]
            fa, wa, cond = [], [], []
            if kind == "text":
                frm = "fts CROSS JOIN docs d ON d.gid=fts.rowid"; cond.append("fts MATCH ?"); wa.append(q.match)
            elif kind == "num":
                frm = f"(SELECT gid FROM nums WHERE field=? AND val{arg[1]}?) x CROSS JOIN docs d ON d.gid=x.gid"
                fa += [f"{q.coll}.{arg[0]}", float(arg[2])]
            elif kind == "near":
                lst = q.nb.get(s)
                if not lst: return empty
                frm = "docs d"
                if len(lst) <= 400:
                    cond.append(f"d.gid IN ({','.join('?' * len(lst))})"); wa += lst
                else:
                    c.execute("CREATE TEMP TABLE IF NOT EXISTS nb(gid INTEGER PRIMARY KEY)")
                    c.execute("DELETE FROM nb")
                    c.executemany("INSERT INTO nb VALUES (?)", [(g,) for g in lst])
                    cond.append("d.gid IN (SELECT gid FROM nb)")
            else:
                frm = "docs d"
            if q.coll: cond.append("d.coll=?"); wa.append(q.coll)
            if q.since is not None: cond.append("d.ts>=?"); wa.append(q.since)
            if q.until is not None: cond.append("d.ts<=?"); wa.append(q.until)
            for p in q.where:
                if kind == "num" and p is arg: continue
                cond.append(f"EXISTS (SELECT 1 FROM nums WHERE gid=d.gid AND field=? AND val{p[1]}?)")
                wa += [f"{q.coll}.{p[0]}", float(p[2])]
            if q.match and kind != "text":
                cond.append("EXISTS (SELECT 1 FROM fts WHERE fts MATCH ? AND rowid=d.gid)"); wa.append(q.match)
            w = (" WHERE " + " AND ".join(cond)) if cond else ""
            if mode == "count":
                return c.execute(f"SELECT COUNT(*) FROM {frm}{w}", fa + wa).fetchone()[0]
            if mode == "agg":
                return c.execute(f"SELECT COUNT(n.val),SUM(n.val),MIN(n.val),MAX(n.val) FROM {frm} "
                                 f"CROSS JOIN nums n ON n.gid=d.gid AND n.field=?{w}",
                                 fa + [f"{q.coll}.{field}"] + wa).fetchone()
            rank = kind == "text" and q.order == "score"
            order = "bm25(fts)" if rank else ("d.ts ASC" if q.order == "oldest" else "d.ts DESC")
            sql = f"SELECT d.gid, d.ts, {'bm25(fts)' if rank else '0.0'} FROM {frm}{w} ORDER BY {order} LIMIT ?"
            return [(g, t, -b) for g, t, b in c.execute(sql, fa + wa + [q.limit])]

    def find(self, coll=None, text=None, where=(), near=None, depth=1, since=None, until=None,
             limit=20, order=None, join=(), docs=True):
        self.flush()
        q = self._q(coll, text, where, near, depth, since, until)
        if q is None: return []
        q.limit, q.order = limit, order or ("score" if q.match else "ts")
        plan = self._plan(q)
        rows = [r for part in self._scatter(lambda s: self._run(s, q, plan, "rows")) for r in part]
        if q.order == "score": rows.sort(key=lambda r: (-r[2], -r[1]))
        elif q.order == "oldest": rows.sort(key=lambda r: r[1])
        else: rows.sort(key=lambda r: -r[1])
        rows = rows[:limit]
        got = self._fetch([r[0] for r in rows], body=docs)
        out = [{"key": got[g][0], "gid": g, "ts": t, "score": sc, **({"doc": _loads(got[g][1])} if docs else {})}
               for g, t, sc in rows if g in got]
        if join and docs: self._join(out, join)
        return out

    def _join(self, rows, fields):
        for f in fields:
            by_rel = collections.defaultdict(list)
            for r in rows:
                rel = self.rels.get(f"{r['key'].split('/', 1)[0]}.{f}")
                if rel is not None: by_rel[rel].append(r)
            for rel, rs in by_rel.items():
                edges = collections.defaultdict(list)
                for s, lst in self._by_shard([r["gid"] for r in rs]).items():
                    with self.locks[s]:
                        for ch in chunks(lst):
                            for src, dst in self.conns[s].execute(
                                    f"SELECT src,dst FROM eout WHERE rel=? AND src IN ({','.join('?' * len(ch))})", [rel.id] + ch):
                                edges[src].append(dst)
                tgt = self._fetch({d for ds in edges.values() for d in ds})
                for r in rs:
                    ds = [_loads(tgt[d][1]) for d in edges[r["gid"]] if d in tgt]
                    r.setdefault("joined", {})[f] = ds if rel.many else (ds[0] if ds else None)

    def count(self, coll=None, text=None, where=(), near=None, depth=1, since=None, until=None):
        self.flush()
        q = self._q(coll, text, where, near, depth, since, until)
        if q is None: return 0
        plan = self._plan(q)
        return sum(self._scatter(lambda s: self._run(s, q, plan, "count")))

    def agg(self, coll, field, text=None, where=(), near=None, depth=1, since=None, until=None):
        """count / sum / min / max / avg of a numeric field over the matching records."""
        self.flush()
        q = self._q(coll, text, where, near, depth, since, until)
        parts = [(0, None, None, None)] if q is None else self._scatter(
            lambda s: self._run(s, q, self._plan(q) if False else plan, "agg", field)) if (plan := self._plan(q)) else []
        n = sum(p[0] for p in parts); tot = sum(p[1] or 0 for p in parts)
        mn = [p[2] for p in parts if p[2] is not None]; mx = [p[3] for p in parts if p[3] is not None]
        return {"count": n, "sum": tot, "min": min(mn) if mn else None, "max": max(mx) if mx else None,
                "avg": tot / n if n else None}

    def query(self, text, limit=20, join=(), docs=True):
        """'in:orders espresso total>=100 since:2026-01-01 near:customers/c1 depth:2 limit:5 order:oldest'"""
        coll, words, where, near, depth, since, until, order = None, [], [], None, 1, None, None, None
        for w in text.split():
            m = _PRED.match(w)
            if m: where.append((m.group(1), m.group(2), float(m.group(3))))
            elif w.startswith("in:"): coll = w[3:]
            elif w.startswith("near:"): near = w[5:]
            elif w.startswith("depth:"): depth = int(w[6:])
            elif w.startswith("since:"): since = w[6:]
            elif w.startswith("until:"): until = w[6:]
            elif w.startswith("limit:"): limit = int(w[6:])
            elif w.startswith("order:"): order = w[6:]
            else: words.append(w)
        return self.find(coll, " ".join(words) or None, where, near, depth, since, until, limit, order, join, docs)

    # ------------------------------------------------------------ heal / stats
    def stats(self):
        self.flush()
        out = collections.Counter()
        for s in range(self.n):
            with self.locks[s]:
                for t in ("docs", "nums", "eout", "ein") + (("fts",) if self.has_fts else ()):
                    out[t] += self.conns[s].execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return dict(out)

    def heal(self, edges_only=False):
        """Re-derive every index from the documents (the truth). edges_only=True: just the 'in' edge index."""
        self.flush()
        before = self.stats()
        if not edges_only:
            def rebuild(s):
                with self._tx(s) as c:
                    c.execute("DELETE FROM nums"); c.execute("DELETE FROM eout")
                    if self.has_fts: c.execute("DELETE FROM fts")
                    cur = c.execute("SELECT gid,coll,body FROM docs")
                    while True:
                        rows = cur.fetchmany(5000)
                        if not rows: break
                        fr, nr, er = [], [], set()
                        for g, cl, b in rows:
                            text, nums, edges = self._derive(cl, _loads(b))
                            if text: fr.append((g, text))
                            nr += [(f, v, g) for f, v in nums]
                            er.update((g, r, gid_of(k)) for r, k in edges)
                        if fr: c.executemany("INSERT INTO fts(rowid,t) VALUES (?,?)", fr)
                        if nr: c.executemany("INSERT OR IGNORE INTO nums VALUES (?,?,?)", sorted(nr))
                        if er: c.executemany("INSERT OR IGNORE INTO eout VALUES (?,?,?)", sorted(er))
            self._scatter(rebuild)
        def clear(s):
            with self._tx(s) as c: c.execute("DELETE FROM ein")
        self._scatter(clear)
        for s in range(self.n):
            last = (-1, -1, -1)
            while True:
                with self.locks[s]:
                    rows = self.conns[s].execute("SELECT src,rel,dst FROM eout WHERE (src,rel,dst) > (?,?,?) "
                                                 "ORDER BY src,rel,dst LIMIT 50000", last).fetchall()
                if not rows: break
                last = rows[-1]
                self._apply_ein([(d, r, sr) for sr, r, d in rows], [])
        after = self.stats()
        return {"docs": after["docs"], "index_rows_changed": {k: after[k] - before[k] for k in after if after[k] != before.get(k)}}

# ======================================================================= demo
def demo():
    db = CleaveDB(":memory:", shards=2)
    db.relate("orders", "customer", "customers")                       # soft link
    db.relate("reviews", "order", "orders", strict=True, on_delete="cascade")
    db.relate("customers", "referred_by", "customers")
    db.index("orders", "total", "qty")
    P = lambda *a: print(*a)
    P("1) fast-moving data: an order arrives BEFORE its customer (soft relationship, late binding)")
    db.put("orders", "o1", {"customer": "c1", "items": "espresso beans and a burr grinder", "total": 120, "qty": 2}, ts="2026-09-01")
    P("   dangling:", db.dangling())
    db.put("customers", "c1", {"name": "Ada", "city": "London", "tier": 3})
    db.put_many("customers", [("c2", {"name": "Bo", "city": "Paris", "tier": 1, "referred_by": "c1"})])
    db.put_many("orders", [("o2", {"customer": "c2", "items": "espresso machine", "total": 899, "qty": 1}, "2026-09-10"),
                           ("o3", {"customer": "c1", "items": "green tea", "total": 15, "qty": 6}, "2026-09-12")])
    P("   dangling after customer arrived:", db.dangling())
    P("2) find + numeric + JOIN (relational feel):")
    for r in db.find("orders", text="espresso", where=[("total", ">=", 100)], join=["customer"]):
        P("  ", r["key"], r["doc"]["total"], "->", r["joined"]["customer"]["name"])
    P("3) reverse traversal: everything pointing at customers/c1:",
      [(r["key"], r["hop"]) for r in db.follow("customers", "c1", "orders.customer", direction="in")])
    P("4) aggregate:", db.agg("orders", "total", where=[("qty", ">=", 1)]))
    P("5) query string:", [r["key"] for r in db.query("in:orders total<200 near:customers/c1 limit:5")])
    P("6) strict relationship rejects a missing target:")
    try: db.put("reviews", "r1", {"order": "nope", "text": "?"})
    except IntegrityError as e: P("  ", e)
    db.put("reviews", "r1", {"order": "o1", "text": "great beans"})
    P("7) cascade delete: delete order o1 ->", db.delete("orders", "o1"), "records; review still there?", db.get("reviews", "r1"))
    P("8) self-heal: corrupt the indexes, then heal()")
    for c in db.conns:
        c.execute("DELETE FROM fts"); c.execute("DELETE FROM ein"); c.execute("DELETE FROM nums WHERE rowid IS NULL OR 1")
    P("   broken  :", [r["key"] for r in db.find("orders", text="espresso")], db.count("orders", where=[("total", ">=", 1)]))
    P("   heal    :", db.heal())
    P("   healed  :", [r["key"] for r in db.find("orders", text="espresso")], db.count("orders", where=[("total", ">=", 1)]))

# ================================================================== self-test
def selftest():
    W = ["coffee", "tea", "mango", "zebra", "piano", "river", "stone", "cloud"]
    for shards in (1, 3):
        for cap in (50, 100000):                        # force both planner paths
            rnd = random.Random(7)
            db = CleaveDB(":memory:", shards=shards, cap=cap)
            db.relate("o", "cust", "c"); db.index("o", "total", "qty")
            docs = {f"o{i}": {"cust": f"c{rnd.randrange(30)}", "note": " ".join(rnd.choices(W, k=4)),
                              "total": round(rnd.random() * 100, 1), "qty": rnd.randint(1, 9)} for i in range(3000)}
            db.put_many("c", [(f"c{i}", {"name": f"n{i}"}) for i in range(30)])
            db.put_many("o", [(k, v, 1000 + i) for i, (k, v) in enumerate(docs.items())])
            def check(label):
                ts = {k: 1000 + i for i, k in enumerate(docs)}
                cases = [
                    dict(text="coffee tea"), dict(where=[("total", ">=", 90)]), dict(where=[("total", ">=", 1)]),
                    dict(text="coffee", where=[("total", "<", 20), ("qty", ">=", 5)], since=1500, until=2500),
                    dict(where=[("qty", "=", 3), ("total", "!=", 50.0)]), dict(near="c/c3"), dict(near="c/c3", where=[("qty", ">", 4)])]
                for kw in cases:
                    def ok(k, d):
                        t = ts[k]
                        if "text" in kw and not all(w in d["note"].split() for w in kw["text"].split()): return False
                        for f, op, v in kw.get("where", []):
                            x = d[f]
                            if not {">": x > v, ">=": x >= v, "<": x < v, "<=": x <= v, "=": x == v, "!=": x != v}[op]: return False
                        if "since" in kw and t < kw["since"]: return False
                        if "until" in kw and t > kw["until"]: return False
                        if "near" in kw and d["cust"] != kw["near"].split("/")[1]: return False
                        return True
                    want = {k for k, d in docs.items() if ok(k, d)}
                    got = {r["key"].split("/")[1] for r in db.find("o", limit=10 ** 6, docs=False, **kw)}
                    assert got == want, (label, shards, cap, kw, len(got), len(want))
                    assert db.count("o", **kw) == len(want), (label, "count", kw)
                    a = db.agg("o", "total", **kw)
                    assert a["count"] == len(want) and abs(a["sum"] - sum(docs[k]["total"] for k in want)) < 1e-6, (label, "agg", kw)
                tops = [r["key"] for r in db.find("o", where=[("qty", ">=", 1)], limit=5)]
                assert tops == ["o/" + k for k in list(docs)[::-1][:5]], (label, "newest-first")
                inc = {r["key"].split("/")[1] for r in db.follow("c", "c3", "o.cust", direction="in")}
                assert inc == {k for k, d in docs.items() if d["cust"] == "c3"}, (label, "follow-in")
            check("fresh")
            for i in range(0, 3000, 7):                  # updates: change totals, text and links
                k = f"o{i}"; docs[k] = {"cust": f"c{(i * 3) % 30}", "note": " ".join(rnd.choices(W, k=4)),
                                         "total": round(rnd.random() * 100, 1), "qty": rnd.randint(1, 9)}
                db.put("o", k, docs[k], ts=1000 + i)
            for i in range(0, 3000, 11):                 # deletes
                assert db.delete("o", f"o{i}") == 1; docs.pop(f"o{i}")
            docs = {k: v for k, v in docs.items()}
            check("after updates+deletes")
            for c in db.conns: c.execute("DELETE FROM fts WHERE rowid % 5 = 0"); c.execute("DELETE FROM ein WHERE src % 4 = 0")
            db.heal(); check("after corruption+heal")
            print(f"ok  shards={shards} cap={cap}  ({len(docs)} docs, 7 query shapes x find/count/agg, updates, deletes, heal)")
            db.close()
    print("ALL TESTS PASSED")

# ================================================================== benchmark
def bench(N=200000, shards=1):
    import tempfile, shutil, statistics
    d = tempfile.mkdtemp()
    W = ["espresso", "coffee", "tea", "grinder", "kettle", "beans", "filter", "mug", "scale", "press", "milk", "cocoa"]
    rnd = random.Random(1)
    db = CleaveDB(d, shards=shards)
    db.relate("orders", "customer", "customers"); db.index("orders", "total", "qty")
    nc = max(N // 10, 10)
    t0 = time.time()
    db.put_many("customers", [(f"c{i}", {"name": f"cust{i}", "city": rnd.choice(["London", "Paris", "Rome"]), "tier": rnd.randint(1, 3)}) for i in range(nc)])
    base = 1.7e9
    for start in range(0, N, 5000):
        db.put_many("orders", [(f"o{i}", {"customer": f"c{rnd.randrange(nc)}", "items": " ".join(rnd.choices(W, k=8)),
                                          "total": round(rnd.random() * 1000, 2), "qty": rnd.randint(1, 5),
                                          "status": rnd.choice(["new", "paid", "shipped"])}, base + i)
                               for i in range(start, min(start + 5000, N))])
    ing = time.time() - t0
    print(f"shards={shards}  {N:,} orders + {nc:,} customers ingested in {ing:.1f}s = {(N + nc) / ing:,.0f} docs/s  (orjson={'yes' if orjson else 'no'})")
    def tm(label, fn, reps=100):
        ts = []
        for i in range(reps):
            t = time.perf_counter(); fn(i); ts.append((time.perf_counter() - t) * 1000)
        ts.sort()
        print(f"  {label:<44} mean {statistics.mean(ts):7.2f} ms   p95 {ts[int(reps * .95) - 1]:7.2f} ms")
    lo = base + N * 0.9
    tm("point get by key", lambda i: db.get("orders", f"o{rnd.randrange(N)}"), 1000)
    tm("text top-10 (2 words, BM25)", lambda i: db.find("orders", text=f"{rnd.choice(W)} {rnd.choice(W)}", limit=10))
    tm("range total>=990, newest 10  (selective)", lambda i: db.find("orders", where=[("total", ">=", 990 - i % 5)], limit=10))
    tm("range total>=10, newest 10   (non-selective)", lambda i: db.find("orders", where=[("total", ">=", 10 + i % 5)], limit=10))
    tm("text + range + time window", lambda i: db.find("orders", text=rnd.choice(W), where=[("total", "<", 50), ("qty", ">=", 4)], since=lo, limit=10))
    tm("range + JOIN customer (10 rows)", lambda i: db.find("orders", where=[("total", ">=", 985)], limit=10, join=["customer"]))
    tm("reverse traversal customer -> orders", lambda i: db.follow("customers", f"c{rnd.randrange(nc)}", "orders.customer", direction="in"))
    tm("count(total>=500 and qty>=3)", lambda i: db.count("orders", where=[("total", ">=", 500), ("qty", ">=", 3)]), 20)
    tm("agg sum(total) where qty>=4", lambda i: db.agg("orders", "total", where=[("qty", ">=", 4)]), 20)
    t = time.time(); r = db.heal(edges_only=True); print(f"  heal(edges_only) over {N:,} orders: {time.time() - t:.1f}s")
    print("  stats:", db.stats(), " disk:", sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)) // 2 ** 20, "MB")
    db.close(); shutil.rmtree(d)

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: demo()
    elif a[0] == "test": selftest()
    elif a[0] == "bench": bench(int(a[1]) if len(a) > 1 else 200000, int(a[2]) if len(a) > 2 else 1)
    else: print(__doc__)
