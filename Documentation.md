# CleaveQL Quick Reference — Complete Command Guide

Seventeen CleaveQL commands, every variant, all bond types, combinations, and chaining recipes.
**Every example was executed against a live CleaveDB instance and returned `status: ok`** (except where an error is shown on purpose).

| # | Command | Purpose | Aliases |
|---|---------|---------|---------|
| 1 | `POUR`     | Create / write documents | — |
| 2 | `FIND`     | Read / query documents and bonds | `SCOOP` |
| 3 | `CHANGE`   | Update fields of a document | `UPDATE` |
| 4 | `DRAIN`    | Soft-delete (moves to `_rubbish`) | — |
| 5 | `LINK`     | Create a bond (graph edge) between documents | `BOND` |
| 6 | `SHOW`     | List buckets, bonds, indexes, stats, webhooks | — |
| 7 | `DESCRIBE` | Summarise a bucket | — |
| 8 | `SHAPE`    | Configure a bucket (audit, versioning, limits) or register a webhook | — |
| 9 | `GUARD`    | Validation rules enforced on writes | — |
| 10 | `INDEX`   | Create an index on bucket fields | — |
| 11 | `TRACE`   | Walk a chain of bonds from a starting document | — |
| 12 | `FOLLOW`  | Explore the graph neighbourhood of a document | — |
| 13 | `FIND PATTERN` | Pattern-match across buckets and bond edges | — |
| 14 | `DISTILL` | Aggregate a bucket (count, sum, average, min, max, spread, group by, where) | — |
| 15 | `HEAL`    | Repair broken bonds and stale data | — |
| 16 | `SUGGEST BONDS` | Propose bonds you haven't created yet | — |
| 17 | `REWIND`  | Restore a document to how it was at an earlier time | — |

Document IDs are written `bucket:id` (e.g. `"users:jane"`). Bonds use these full IDs.

---

## 1. POUR — create documents

```sql
POUR INTO users "jane" {"name": "Jane", "age": 25, "city": "Manila"}
```

| Variant | Syntax |
|---------|--------|
| Explicit ID | `POUR INTO users "juan" {"name": "Juan"}` |
| Quoted bucket | `POUR INTO "users" "pedro" {"name": "Pedro"}` |
| Auto-generated ID | `POUR INTO users RANDOM {"name": "Rand"}` |
| Bulk insert | `POUR MANY INTO users [{"name": "A"}, {"name": "B"}]` |
| Expiring document (TTL) | `POUR INTO sessions "s1" {"user": "jane"} EXPIRES IN 30 MINUTES` |
| With login secret | `POUR INTO vault "k1" {"token": "abc"} WITH SECRET "mykey"` |
| Write into a nested field | `POUR '{"nick": "JJ"}' INSIDE users "jane" AT profile` |

- TTL units: `SECONDS`, `MINUTES`, `HOURS`, `DAYS`.
- `INSIDE ... AT` takes the JSON as a **quoted string** and sets `profile` on the existing document.
- `POUR MANY` checks `GUARD` rules for **every** document first; if one is rejected, nothing is written.

---

## 2. FIND — query

```sql
FIND users
```

### 2a. Documents

| Variant | Syntax |
|---------|--------|
| All documents | `FIND users` · `FIND FROM users` · `FIND EVERYTHING FROM users` |
| By ID | `FIND users "jane"` |
| Filter | `FIND users WHERE age > 20` |
| Multiple conditions | `FIND users WHERE age > 20 AND city = "Manila"` |
| OR | `FIND users WHERE age < 20 OR city = "Cebu"` |
| Exact field | `FIND users WHOSE name IS "Jane"` |
| JSON match | `FIND users MATCHING {"city": "Manila"}` |
| Sort | `FIND users ARRANGED BY age GOING DOWN` (also `ORDER BY … GOING UP`, `SORTED BY age DESC`) |
| Limit | `FIND users LIMIT 2` |
| Pick fields | `FIND users YIELD name, age` (also `SHOW name`) |
| Combined | `FIND users WHERE age > 10 ARRANGED BY age GOING DOWN LIMIT 2` |

Operators: `=`, `!=`, `>`, `<`, `>=`, `<=`, joined with `AND` / `OR`.

### 2b. Summaries

| Variant | Syntax |
|---------|--------|
| Distinct values | `FIND ONLY UNIQUE city FROM users` |
| First N / last N | `FIND THE FIRST 2 FROM users` · `FIND THE LAST 2 FROM users` |
| Count | `FIND THE TALLY OF users` |
| Top N by field | `FIND THE HIGHEST 2 age FROM users` |
| Bottom N by field | `FIND THE LOWEST 2 age FROM users` |

### 2c. Bonds (graph lookups)

| Variant | Syntax |
|---------|--------|
| Related docs | `FIND "crush" OF "users:jane"` |
| Legacy form | `FIND RELATED "friend" FROM "users:jane"` |
| Include inactive conditional bonds | `FIND CANDIDATE "cond" OF "users:jane"` |
| Bonds as they were | `FIND "friend" OF "users:jane" AS OF "yesterday"` |
| Multi-hop chain | `FIND THE knows OF THE boss OF users "jane"` |

Notes:
- Results are de-duplicated by target document.
- Documents that were `DRAIN`ed (sitting in `_rubbish`) are **not** returned.
- A chain reads right-to-left: the label closest to the bucket is followed first. `FIND THE knows OF THE boss OF users "jane"` = *whom does Jane's boss know?*

---

## 3. CHANGE — update fields

```sql
CHANGE users "jane" SET age TO 26
```

| Variant | Syntax |
|---------|--------|
| Single field | `CHANGE users "jane" SET age TO 26` |
| Multiple fields | `CHANGE users "jane" SET age TO 27, city TO "Quezon"` |
| ID-first form | `CHANGE "jane" IN users TO age = 28` |
| ID-first, multiple | `CHANGE "jane" IN users SET age = 29, city = "Makati"` |
| Alias | `UPDATE users "juan" SET age TO 31` |

- Only the listed fields change; the rest of the document is preserved.
- `GUARD` rules are enforced on `CHANGE` too.
- Negative numbers aren't accepted as `CHANGE` values (`SET age TO -5` is a parse error); use `POUR` with the full document instead.

---

## 4. DRAIN — soft-delete

```sql
DRAIN users "pedro"
```

| Variant | Syntax |
|---------|--------|
| One document | `DRAIN users "pedro"` |
| By condition | `DRAIN users WHERE age < 5` |
| By condition (AND / OR) | `DRAIN emp WHERE dept = "HR" AND age > 26` · `DRAIN emp WHERE age < 20 OR dept = "Ops"` |
| By age | `DRAIN users BEFORE "2000-01-01"` |

Drained documents go to `_rubbish` and their bonds are cascaded. Companions:

| Command | Effect |
|---------|--------|
| `SALVAGE "pedro"` | Restore one drained document (its bonds come back too) |
| `SALVAGE EVERYTHING` | Restore all drained documents |
| `INCINERATE "pedro"` | Permanently delete one from `_rubbish` |
| `INCINERATE EVERYTHING` | Empty `_rubbish` |

---

## 5. LINK — create bonds

```sql
LINK "users:jane" TO "users:juan" AS "crush"
```

### 5a. Basic bond forms

| Form | Syntax |
|------|--------|
| Labelled bond | `LINK "users:jane" TO "users:juan" AS "friend"` |
| Default label (`linked`) | `LINK "users:jane" TO "users:juan"` |
| Several targets | `LINK "users:jane" TO "users:juan", "users:pedro" AS "knows"` |
| `ANY(...)` targets | `LINK "users:jane" TO ANY("users:juan", "users:pedro") AS "any_rel"` |
| Two-way (mutual) | `LINK "users:jane" AND "users:pedro" AS MUTUAL "bff"` |
| Alias | `BOND "users:juan" TO "users:pedro" AS "boss"` |

### 5b. Bond modifiers

Append after `AS "label"`. All can be combined on a single `LINK`.

| Modifier | Syntax | Effect |
|----------|--------|--------|
| Confidence score | `WITH CONFIDENCE 0.9` | Stores a 0–1 strength score on the bond |
| Affinity score | `WITH AFFINITY 0.8` | Stores a 0–1 closeness score on the bond |
| Both scores | `WITH CONFIDENCE 0.9 WITH AFFINITY 0.7` | Both scores on one bond |
| Expiry (seconds) | `EXPIRING IN 30 SECONDS` | Bond auto-expires after 30 s |
| Expiry (minutes) | `EXPIRING IN 5 MINUTES` | Bond auto-expires after 5 min |
| Expiry (hours) | `EXPIRING IN 2 HOURS` | Bond auto-expires after 2 h |
| Exclusive | `EXCLUSIVELY` | Replaces any previous bond with the same label from this source |
| Cascade on delete | `ON DELETE CASCADE` | When source is `DRAIN`ed, target is also drained |
| Through bucket | `THROUGH hubs` | Tags the bond with an intermediate bucket reference |

### 5c. Conditional bonds

Bonds that only activate when a field condition on the target (or source) is met.

| Condition | Syntax | Checked against |
|-----------|--------|-----------------|
| Target field (default) | `IF status = "active"` | Target document's field |
| `ONLY WHEN` synonym | `ONLY WHEN status IS "active"` | Target document's field |
| Source field (`source`) | `IF source role IS "admin"` | Source document's field |
| Source field (`my`) | `IF my role = "admin"` | Source document's field |
| Target field (`their`) | `IF their role = "user"` | Target document's field |
| Numeric field | `IF age = 25` | Target document's field |

**How conditional bonds behave:**

```sql
-- Create a conditional bond
LINK "staff:a" TO "staff:d" AS "gate" IF status = "active"

-- d.status is "active" → bond is live
FIND "gate" OF "staff:a"                -- 1 result

-- Change the field so the condition fails
CHANGE staff "d" SET status TO "inactive"
FIND "gate" OF "staff:a"                -- 0 results (condition not met)
FIND CANDIDATE "gate" OF "staff:a"      -- shows the bond with status "candidate"

-- Fix the field → bond activates again
CHANGE staff "d" SET status TO "active"
FIND "gate" OF "staff:a"                -- 1 result again
```

### 5d. Fully-loaded bond (all modifiers at once)

```sql
LINK "staff:a" TO "staff:b" AS "full"
  IF status = "active"
  WITH CONFIDENCE 0.9
  EXPIRING IN 2 HOURS
  ON DELETE CASCADE
  EXCLUSIVELY
```

### 5e. Special bond cases

| Case | Syntax | Behaviour |
|------|--------|-----------|
| Self-referencing | `LINK "users:ann" TO "users:ann" AS "self"` | Document bonds to itself |
| Ghost bond | `LINK "users:ann" TO "users:ghost" AS "ghost"` | Bonds to a non-existent doc (FIND returns 0 results) |
| Duplicate bonds | `LINK "a:1" TO "a:2" AS "dup"` twice | Both stored; `FIND` deduplicates by target |

### 5f. Exclusive bonds — replacing previous targets

```sql
LINK "staff:a" TO "staff:b" AS "primary" EXCLUSIVELY
LINK "staff:a" TO "staff:c" AS "primary" EXCLUSIVELY   -- replaces the b→ bond
FIND "primary" OF "staff:a"                             -- returns only staff:c
```

### 5g. Expiring bonds

```sql
LINK "staff:a" TO "staff:b" AS "temp" EXPIRING IN 1 SECONDS
FIND "temp" OF "staff:a"      -- 1 result (immediately after)
-- wait 2 seconds …
FIND "temp" OF "staff:a"      -- 0 results (expired)
```

### 5h. Cascade on delete

```sql
LINK "staff:a" TO "staff:b" AS "cascade_demo" ON DELETE CASCADE
DRAIN staff "a"                -- also drains staff:b
```

### Removing bonds — SEVER

```sql
SEVER "users:jane" FROM "users:juan" AS "friend"
```

| Variant | Syntax |
|---------|--------|
| One label | `SEVER "users:jane" FROM "users:juan" AS "friend"` |
| Alias | `UNLINK "users:jane" FROM "users:juan" AS "crush"` |
| All labels between the pair | `SEVER "users:jane" FROM "users:pedro"` |

`SEVER` matches the pair in **either direction**, so argument order doesn't matter. Without `AS`, it removes **every** bond between the two documents.

---

## 6. SHOW — list things

| Syntax | Returns |
|--------|---------|
| `SHOW BUCKETS` | Your bucket names: `{"data": ["emp", "mix"]}` |
| `SHOW BONDS` | Every bond: `{"count": 1, "data": [{…}]}` |
| `SHOW INDEXES` | Every index: `{"count": 1, "data": [{…}]}` |
| `SHOW STATS` | Totals: `{"buckets": 1, "documents": 3, "bonds": 1, "per_bucket": {"emp": 3}}` |
| `SHOW WEBHOOKS` | Webhooks: `{"count": 1, "data": [{…}]}` |

Results only include your own data. Internal `_` buckets are hidden unless you log in with the dev password.

---

## 7. DESCRIBE — summarise a bucket

```sql
DESCRIBE emp
```
Returns e.g. `Bucket 'emp' (7 docs). Stats computed successfully.` A bucket with no documents returns `Bucket 'nosuch' is empty.`

---

## 8. SHAPE — configure buckets and webhooks

```sql
SHAPE BUCKET orders AUDITED
```

| Variant | Syntax |
|---------|--------|
| Audit every change | `SHAPE BUCKET orders AUDITED` |
| Keep versions | `SHAPE BUCKET orders VERSIONED` |
| Cap document count | `SHAPE BUCKET orders MAX DOCUMENTS 100` |
| Compression | `SHAPE BUCKET orders COMPRESSION zstd` |
| Expiry | `SHAPE BUCKET orders TTL 3600` |
| Several at once | `SHAPE BUCKET orders VERSIONED AUDITED MAX DOCUMENTS 50` |
| Short form | `SHAPE orders AUDITED` |
| Webhook on writes | `SHAPE WEBHOOK "hook1" ON orders WHEN ACTION = "POUR" POST TO "http://example.com/hook"` |

- Each option updates the bucket's saved policy; repeating `SHAPE` adds to it.
- With `AUDITED`, changes are logged to `_audit_<bucket>` (e.g. `FIND _audit_orders`). Reading it **requires the dev password**; a normal login gets `Access Denied`.
- List webhooks with `SHOW WEBHOOKS`.

---

## 9. GUARD — validation rules

```sql
GUARD people WITH name IS REQUIRED, age >= 0, role IN ("admin", "user")
```

| Rule | Syntax |
|------|--------|
| Field must exist | `name IS REQUIRED` |
| Field must not exist | `nick IS NOT REQUIRED` |
| Comparison | `age >= 0` (also `>`, `<`, `<=`, `=`, `!=`) |
| One of a list | `role IN ("admin", "user")` |
| Type check | `age IS TYPE number` |

Rules are comma-separated, and later `GUARD` statements for the same bucket **add** to the existing rules. Once set, violating writes are rejected:

```text
POUR INTO people "p2" {"age": 5, "role": "user"}
  → Guard violation on 'people': 'name' is required
POUR INTO people "p3" {"name": "Neg", "age": -1, "role": "user"}
  → Guard violation on 'people': 'age' must be >= 0
POUR INTO people "p4" {"name": "BadRole", "age": 5, "role": "boss"}
  → Guard violation on 'people': 'role' must be one of ['admin', 'user']
```

Enforced on `POUR`, `POUR MANY` and `CHANGE`.

---

## 10. INDEX — speed up lookups

```sql
INDEX age ON emp
```

| Variant | Syntax |
|---------|--------|
| One field | `INDEX age ON emp` · `INDEX emp ON (age)` |
| Several fields | `INDEX dept, age ON emp` · `INDEX emp ON (dept, age)` |

Check with `SHOW INDEXES`. Running the same `INDEX` twice creates a duplicate entry.

---

## 11. TRACE — walk a bond chain

Follow a sequence of labelled bonds from a starting document, returning every document visited along the way.

```sql
TRACE "reports_to" FROM "staff:bob"
```

| Variant | Syntax | Effect |
|---------|--------|--------|
| Single label | `TRACE "reports_to" FROM "staff:bob"` | Walk `reports_to` edges one hop at a time until there are no more |
| Multi-label chain | `TRACE "reports_to", "reports_to" FROM "staff:bob"` | Walk exactly 2 hops of `reports_to` |
| Mixed labels | `TRACE "manages", "mentors" FROM "staff:ana"` | First hop follows `manages`, second hop follows `mentors` |

```sql
-- Setup: bob →reports_to→ di →reports_to→ cy
LINK "staff:bob" TO "staff:di" AS "reports_to"
LINK "staff:di" TO "staff:cy" AS "reports_to"

TRACE "reports_to" FROM "staff:bob"
-- Returns the chain: bob → di → cy

TRACE "reports_to", "reports_to" FROM "staff:bob"
-- Same result, but explicitly asks for exactly 2 hops
```

---

## 12. FOLLOW — explore graph neighbourhood

Explore which documents are reachable from a starting point, optionally filtering by bond label, direction, and depth.

```sql
FOLLOW "staff:ana" THROUGH "manages"
```

| Variant | Syntax |
|---------|--------|
| All bonds (any label) | `FOLLOW "staff:ana"` |
| Through a specific label | `FOLLOW "staff:ana" THROUGH "manages"` |
| Unquoted label | `FOLLOW "staff:ana" THROUGH manages` |
| Outgoing only | `FOLLOW "staff:ana" THROUGH "manages" DIRECTION OUT` |
| Incoming only | `FOLLOW "staff:bob" THROUGH "manages" DIRECTION IN` |
| Both directions | `FOLLOW "staff:ana" THROUGH "manages" DIRECTION BOTH` |
| Multi-hop depth | `FOLLOW "staff:bob" THROUGH "reports_to" DEPTH 2` |
| Depth + limit | `FOLLOW "staff:bob" THROUGH "reports_to" DEPTH 2 LIMIT 1` |
| Sort results | `FOLLOW "staff:ana" THROUGH "manages" ARRANGED BY age GOING DOWN LIMIT 2` |
| Historical view | `FOLLOW "staff:ana" THROUGH "manages" AS OF "yesterday"` |

```sql
-- ana manages bob and cam; bob reports_to cam
FOLLOW "staff:ana" THROUGH "manages"
-- Returns: bob, cam (1 hop out)

FOLLOW "staff:bob" THROUGH "manages" DIRECTION IN
-- Returns: ana (who manages bob)

FOLLOW "staff:bob" THROUGH "reports_to" DEPTH 2
-- Returns: cam, dee (2-hop chain)
```

---

## 13. FIND PATTERN — graph pattern matching

Match subgraph patterns across buckets and bond edges. Each node is aliased (`AS x`), and you specify the bond label with `LINKED VIA`.

```sql
FIND PATTERN IN staff AS x LINKED VIA "manages" TO staff AS y
```

### Edge directions

| Direction | Syntax | Meaning |
|-----------|--------|---------|
| Outgoing (`→`) | `… LINKED VIA "manages" TO staff AS y` | x manages y |
| Incoming (`←`) | `… LINKED VIA "manages" FROM staff AS boss` | boss manages x |
| Undirected (`↔`) | `… LINKED VIA "partner" WITH staff AS y` | mutual / either direction |

### Variants

| Pattern | Syntax |
|---------|--------|
| Two-node, outgoing | `FIND PATTERN IN staff AS x LINKED VIA "manages" TO staff AS y` |
| With `IN` keyword | `FIND PATTERN IN staff AS x LINKED VIA "manages" TO staff AS y` |
| Without `IN` keyword | `FIND PATTERN staff AS x LINKED VIA "manages" TO staff AS y` |
| Filter on alias | `FIND PATTERN staff AS x LINKED VIA "manages" TO staff AS y WHERE x.role = "lead"` |
| Three-node chain | `FIND PATTERN staff AS a LINKED VIA "manages" TO staff AS b LINKED VIA "mentors" TO staff AS c` |
| Incoming edge | `FIND PATTERN staff AS x LINKED VIA "manages" FROM staff AS boss` |
| Undirected edge | `FIND PATTERN staff AS x LINKED VIA "peer" WITH staff AS y` |
| Cross-bucket | `FIND PATTERN staff AS x LINKED VIA "lives_in" TO places AS p` |

```sql
-- Who does Ana manage that also mentors someone?
FIND PATTERN staff AS a LINKED VIA "manages" TO staff AS b LINKED VIA "mentors" TO staff AS c
-- Result: a=Ana → b=Ben → c=Dee

-- Cross-bucket: which staff live where?
FIND PATTERN staff AS s LINKED VIA "lives_in" TO places AS p
-- Result: s=Ana → p=Manila (or Cebu, depending on bonds)
```

---

## 14. DISTILL — aggregate a bucket

Run aggregation functions on a bucket's documents without returning individual records.

```sql
DISTILL FROM staff TOTAL age
```

| Aggregation | Syntax | Result key |
|-------------|--------|------------|
| Sum | `DISTILL FROM staff TOTAL age` | `total` |
| Sum (alias) | `DISTILL FROM staff SUM age` | `sum` |
| Average | `DISTILL FROM staff AVERAGE OF age` · `AVERAGE age` | `average` |
| Average (short) | `DISTILL FROM staff AVG age` | `avg` |
| Minimum | `DISTILL FROM staff MIN age` | `min` |
| Maximum | `DISTILL FROM staff MAX age` | `max` |
| Spread (max − min) | `DISTILL FROM staff SPREAD age` | `spread` |
| Count documents | `DISTILL FROM staff COUNT` · `DISTILL FROM staff TALLY` | `count` / `tally` |
| Count documents that have a field | `DISTILL FROM staff COUNT status` · `TALLY OF status` | `count` / `tally` |

- `COUNT` and `TALLY` are the same. With no field they count documents; with a field they count documents where that field is present (any type).
- All other aggregations use numeric values only.
- An unknown function returns `Unknown aggregation: BOGUS`.
- If no document matches (or the bucket doesn't exist) the result is `[]` with `count: 0`.

### AS — name the result

```sql
DISTILL FROM staff COUNT AS headcount
DISTILL FROM staff TOTAL age AS payroll_age
```

### Several aggregates at once (comma-separated)

```sql
DISTILL FROM staff TOTAL age AS total, MIN age AS youngest, MAX age AS oldest, COUNT AS n
```
Returns `{"total": 119.0, "youngest": 24, "oldest": 35, "n": 4}`.

### WHERE — aggregate only some documents

`WHERE` accepts the same conditions as `FIND` (`=`, `!=`, `>`, `<`, `>=`, `<=`, joined with `AND` / `OR`). It can go right after the bucket, after `GROUP BY`, or at the end.

```sql
DISTILL FROM staff WHERE dept = "Eng" TOTAL age
DISTILL FROM staff WHERE age > 25 COUNT
DISTILL FROM staff WHERE dept = "Eng" AND age > 30 COUNT
DISTILL FROM staff WHERE dept = "Eng" OR age < 5 TALLY AS n
DISTILL FROM staff COUNT WHERE status = "active"
```

### GROUP BY

Group results by a field, then aggregate within each group.

```sql
DISTILL FROM staff GROUP BY dept TOTAL age AS total_age
```

Returns:
```json
[
  {"dept": "Eng", "total_age": 63.0},
  {"dept": "Ops", "total_age": 56.0}
]
```

```sql
DISTILL FROM staff GROUP BY dept COUNT AS n
DISTILL FROM staff GROUP BY dept AVERAGE age
DISTILL FROM staff GROUP BY role TOTAL age AS total, AVERAGE age AS avg
DISTILL FROM staff GROUP BY dept WHERE age > 25 COUNT AS n
DISTILL FROM staff GROUP BY dept WHERE age > 30 TOTAL age AS t, COUNT AS n
DISTILL FROM staff GROUP BY dept TOTAL age AS t WHERE status = "active"
```

The bucket name may be quoted: `DISTILL FROM "staff" COUNT`.

---

## 15. HEAL — repair integrity

Clean up dangling bonds (pointing to deleted/non-existent documents) and other stale data.

```sql
HEAL BONDS
```

| Variant | Syntax | Effect |
|---------|--------|--------|
| Bonds only | `HEAL BONDS` | Removes bonds whose source or target no longer exists |
| Full repair | `HEAL ALL` | Heals bonds plus any other detectable inconsistencies |

Use `HEAL` after bulk deletes or when ghost bonds accumulate.

---

## 16. SUGGEST BONDS — find bonds you haven't made yet

Scans your documents and proposes bonds that are likely missing. It **only suggests** — nothing is created until you `LINK`.

```sql
SUGGEST BONDS
```

Example result:

```json
{"status": "ok", "count": 2, "suggestions": [
  {"source": "logs:l3", "target": "staff:c", "confidence": 0.95, "reason": "Field 'owner' references staff:c"},
  {"source": "logs:l1", "target": "staff:a", "confidence": 0.75, "reason": "Field 'user' matches the id of staff:a"}
]}
```

| Signal | Confidence | Example |
|--------|-----------|---------|
| A field holds a full document id | 0.95 | `{"owner": "staff:c"}` |
| A field holds the id of a document in another bucket | 0.75 | `{"user": "a"}` matches `staff:a` |
| Vector similarity in `_embeddings` | similarity score (> 0.5) | semantic closeness |

- Pairs that are already bonded (in either direction) are **not** suggested again.
- Suggestions are sorted by confidence; an empty list means nothing is missing.

```sql
SUGGEST BONDS                                          -- 1. see what's missing
LINK "logs:l1" TO "staff:a" AS "by"                    -- 2. accept a suggestion
SUGGEST BONDS                                          -- 3. it no longer appears
FIND "by" OF "logs:l1"                                 -- 4. use the new bond
```

All in one line: `SUGGEST BONDS LINK "logs:l1" TO "staff:b" AS "seen" SUGGEST BONDS`.

---

## 17. REWIND — restore a document to an earlier time

Puts a document back to the state it had at a given moment.

```sql
SHAPE BUCKET staff AUDITED        -- required once, BEFORE the changes you want to undo
CHANGE staff "a" SET age TO 36
CHANGE staff "a" SET age TO 37
REWIND "staff:a" TO "1 minutes ago"
```

| Variant | Syntax |
|---------|--------|
| Relative time | `REWIND "staff:a" TO "10 minutes ago"` · `"2 hours ago"` · `"yesterday"` |
| Absolute time | `REWIND "staff:a" TO "2026-10-05 14:30"` |
| Current state | `REWIND "staff:a" TO "now"` |
| Unix timestamp | `REWIND "staff:a" TO "1791191933"` |

Rules:
- The bucket must be `AUDITED` (or `VERSIONED`) **before** the changes happen — `REWIND` reads that history. Otherwise: `No history for 'staff:a'. Run SHAPE BUCKET staff AUDITED …`.
- The document id must be the full `bucket:id` form.
- If the document did not exist at that time you get `'staff:a' did not exist at that time.` and nothing changes.
- The rewind is itself logged, so you can `REWIND` again (e.g. to undo the rewind).
- Bonds are left untouched — they keep pointing at the document.

```sql
REWIND "staff:a" TO "1 minutes ago"
FIND staff "a"                                         -- shows the restored fields
FIND "pal" OF "staff:a"                                -- bonds still intact
```

---

## Combining the core commands

### FIND — mixing filters, sorting, limits and projection

```sql
FIND emp WHERE dept = "IT" AND age > 30 ARRANGED BY age GOING DOWN
FIND emp WHERE dept = "IT" YIELD name, age ARRANGED BY age GOING UP LIMIT 2
FIND emp WHOSE dept IS "HR" YIELD name
FIND emp MATCHING {"dept": "IT"} LIMIT 1
FIND emp MATCHING {"dept": "IT"} YIELD name
FIND emp "e1" YIELD name, age
SCOOP emp WHERE dept = "IT" ARRANGED BY age GOING DOWN LIMIT 1
```

Summaries accept a `WHERE` filter:

```sql
FIND THE FIRST 2 FROM emp WHERE dept = "IT"
FIND THE HIGHEST 1 age FROM emp WHERE dept = "IT"
FIND THE LOWEST 2 age FROM emp WHERE dept = "HR"
FIND THE TALLY OF emp WHERE dept = "IT"
```

### POUR + CHANGE + FIND — write, edit, read back

```sql
CHANGE emp "e1" SET age TO 36, dept TO "Ops"
FIND emp "e1"
FIND emp WHERE dept = "Ops"
```

### LINK — combining modifiers

```sql
LINK "emp:e1" TO "emp:e2" AS "mentor" WITH CONFIDENCE 0.9 EXPIRING IN 2 HOURS
FIND "mentor" OF "emp:e1"                      -- result carries "confidence": 0.9
LINK "emp:e1" AND "emp:e2" AS MUTUAL "peer" WITH AFFINITY 0.7
FIND "peer" OF "emp:e2"                        -- works from either side
LINK "emp:e1" TO ANY("emp:e2") AS "rep" EXCLUSIVELY
LINK "emp:e1" TO "emp:e2", "emp:e1" AS "many" WITH CONFIDENCE 0.5
```

### LINK + CHANGE + FIND — conditional bonds follow the data

```sql
LINK "emp:e1" TO "emp:e2" AS "gate" IF role = "admin" ON DELETE CASCADE
FIND "gate" OF "emp:e1"                        -- e2.role is "admin": 1 result, status "active"
CHANGE emp "e2" SET role TO "user"
FIND "gate" OF "emp:e1"                        -- condition no longer true: 0 results
FIND CANDIDATE "gate" OF "emp:e1"              -- shown again, with status "candidate"
CHANGE emp "e2" SET role TO "admin"
FIND "gate" OF "emp:e1"                        -- active again
```

### DRAIN + SALVAGE + LINK — bonds travel with their documents

```sql
DRAIN emp WHERE dept = "HR" AND age > 26       -- drained doc's bonds disappear from FIND
FIND "mentor" OF "emp:e1"                      -- 0 results
SALVAGE "e2"                                   -- document back ...
FIND "mentor" OF "emp:e1"                      -- ... and so is the bond
```

### DRAIN + CASCADE — deleting propagates through bonds

```sql
LINK "staff:a" TO "staff:b" AS "backup" ON DELETE CASCADE
DRAIN staff "a"                                -- also drains staff:b (cascade)
FIND "backup" OF "staff:a"                     -- 0 results, both gone
```

### SEVER — one label, then everything

```sql
SEVER "emp:e1" FROM "emp:e2" AS "peer"         -- removes both directions of the mutual bond
SEVER "emp:e1" FROM "emp:e2"                   -- removes every remaining bond between them
```

### TRACE + FIND PATTERN — verify a chain with pattern matching

```sql
-- Set up a chain: bob →reports_to→ di →reports_to→ cy
LINK "staff:bob" TO "staff:di" AS "reports_to"
LINK "staff:di" TO "staff:cy" AS "reports_to"

-- Walk the chain
TRACE "reports_to" FROM "staff:bob"            -- returns [bob, di, cy]

-- Verify with pattern matching
FIND PATTERN staff AS a LINKED VIA "reports_to" TO staff AS b LINKED VIA "reports_to" TO staff AS c
-- Returns: a=bob, b=di, c=cy
```

### TRACE + mixed labels — cross-label traversal

```sql
LINK "staff:ana" TO "staff:bob" AS "manages"
LINK "staff:bob" TO "staff:dee" AS "mentors"

TRACE "manages", "mentors" FROM "staff:ana"    -- ana →manages→ bob →mentors→ dee
```

### FOLLOW + DIRECTION + DEPTH — full graph walk

```sql
-- Outgoing only
FOLLOW "staff:ana" THROUGH "manages" DIRECTION OUT      -- bob, cam

-- Incoming: who manages bob?
FOLLOW "staff:bob" THROUGH "manages" DIRECTION IN       -- ana

-- Both directions
FOLLOW "staff:ana" THROUGH "manages" DIRECTION BOTH     -- bob, cam

-- Multi-hop walk
FOLLOW "staff:bob" THROUGH "reports_to" DEPTH 2         -- cam, dee

-- Walk + sort + limit
FOLLOW "staff:ana" THROUGH "manages" ARRANGED BY age GOING DOWN LIMIT 2
```

### FOLLOW then DISTILL — explore then aggregate

```sql
FOLLOW "staff:ana" THROUGH "manages"                    -- see who's under Ana
DISTILL FROM staff GROUP BY dept TOTAL age AS total_age  -- aggregate the whole bucket
```

### FIND PATTERN cross-bucket — staff → places

```sql
LINK "staff:ana" TO "places:mnl" AS "lives_in"
FIND PATTERN staff AS s LINKED VIA "lives_in" TO places AS p
-- Returns: s=ana, p=Manila
```

### FIND PATTERN undirected — mutual bonds

```sql
LINK "staff:ana" AND "staff:eve" AS MUTUAL "peer"
FIND PATTERN staff AS x LINKED VIA "peer" WITH staff AS y
-- Returns paths from both sides
```

### FIND HOW — bond history (drift)

```sql
LINK "staff:ana" TO "staff:bob" AS "manages"
LINK "staff:ana" TO "staff:cam" AS "manages"

FIND HOW THE "manages" OF "staff:ana" CHANGED BETWEEN "yesterday" AND "tomorrow"
-- Returns: [{action: "LINK", target: "staff:bob"}, {action: "LINK", target: "staff:cam"}]

SEVER "staff:ana" FROM "staff:cam" AS "manages"

FIND HOW THE "manages" OF "staff:ana" CHANGED BETWEEN "2000-01-01" AND "2999-01-01"
-- Now includes: [{action: "LINK", …}, {action: "LINK", …}, {action: "SEVER", target: "staff:cam"}]
```

### Multi-command one-liner — POUR + LINK + FIND

```sql
POUR INTO staff "f" {"name":"Fay","role":"dev","dept":"Eng","age":22} LINK "staff:a" TO "staff:f" AS "manages" FIND "manages" OF "staff:a"
```

### SHOW + INDEX + GUARD + SHAPE together

```sql
GUARD staff WITH name IS REQUIRED, age >= 0
INDEX age ON staff
INDEX staff ON (dept, role)
SHAPE BUCKET staff AUDITED VERSIONED
SHOW INDEXES
SHOW STATS
DESCRIBE staff
```

---

### DISTILL + WHERE + GROUP BY — slice, then aggregate

```sql
DISTILL FROM staff WHERE status = "active" GROUP BY dept TOTAL age AS total, COUNT AS n
DISTILL FROM staff GROUP BY dept WHERE age > 30 TOTAL age AS t, COUNT AS n
DISTILL FROM staff COUNT WHERE dept = "Eng" OR age < 5
```

### DISTILL after changes — numbers follow the data

```sql
CHANGE staff "a" SET age TO 51
DISTILL FROM staff MAX age                     -- {"max": 51}
DRAIN staff "a"
DISTILL FROM staff COUNT                       -- drained documents are not counted
```

### SUGGEST BONDS + LINK + FOLLOW — discover, accept, explore

```sql
SUGGEST BONDS                                  -- logs:l1 → staff:a (field 'user' matches id 'a')
LINK "logs:l1" TO "staff:a" AS "by"
SUGGEST BONDS                                  -- that pair is gone from the list
FOLLOW "logs:l1" THROUGH "by"                  -- returns logs:l1 and staff:a
FIND "by" OF "logs:l1"
```

### REWIND + AUDITED/VERSIONED + DISTILL — undo and re-measure

```sql
SHAPE BUCKET staff VERSIONED
CHANGE staff "a" SET age TO 36
CHANGE staff "a" SET age TO 37
REWIND "staff:a" TO "1 seconds ago"            -- back to 36
FIND staff "a"
DISTILL FROM staff TOTAL age                   -- totals use the restored value
```

### REWIND + LINK — bonds survive a rewind

```sql
LINK "staff:a" TO "staff:b" AS "pal"
CHANGE staff "a" SET age TO 50
REWIND "staff:a" TO "now"
FIND "pal" OF "staff:a"                        -- bond still there
```

### One line — write, rewind, aggregate

```sql
CHANGE staff "a" SET age TO 51 REWIND "staff:a" TO "now" DISTILL FROM staff MAX age
```

---

## Chaining commands

### A. Several commands in one line
Statements are executed in order and return one result each. No separator is needed. All commands can be mixed:

```sql
POUR INTO mix "m1" {"v": 1} POUR INTO mix "m2" {"v": 2} LINK "mix:m1" TO "mix:m2" AS "next" FIND "next" OF "mix:m1" CHANGE mix "m2" SET v TO 5 FIND mix WHERE v > 1 SEVER "mix:m1" FROM "mix:m2" AS "next" DRAIN mix "m2" FIND mix
```

```sql
POUR INTO chain "c3" {"v": 3} CHANGE chain "c3" SET v TO 99 FIND chain "c3" DRAIN chain "c3"
```

```sql
LINK "chain:c1" TO "chain:c2" AS "next" LINK "chain:c2" TO "chain:c1" AS "next" FIND "next" OF "chain:c1" SEVER "chain:c1" FROM "chain:c2" AS "next" FIND "next" OF "chain:c1"
```
The final `FIND` returns 0 documents — the bond is gone.

A write can be followed by a `PIPE` query in the same line:

```sql
POUR INTO emp "z1" {"name": "Zed", "age": 50, "dept": "IT"} PIPE FROM emp THEN WHERE age > 45 THEN SHOW name
```

### B. Transactions

```sql
BEGIN TRANSACTION POUR INTO users "t1" {"name": "T1"} POUR INTO users "t2" {"name": "T2"} COMMIT TRANSACTION
```

```sql
BEGIN TRANSACTION POUR INTO mix "m3" {"v": 3} LINK "mix:m3" TO "mix:m1" AS "tx" CHANGE mix "m3" SET v TO 4 COMMIT TRANSACTION
```

```sql
BEGIN TRANSACTION POUR INTO users "t3" {"name": "T3"} ROLLBACK TRANSACTION
```
After the `ROLLBACK`, `FIND users "t3"` returns 0 documents.

> **Limitation:** `ROLLBACK` only undoes `POUR` / `POUR MANY` writes. `CHANGE`, `LINK`, `SEVER` and `DRAIN` run inside a transaction are **not** reverted. Use transactions for groups of `POUR`s.

### C. Multi-hop bond chains
Follow bonds across several hops in one `FIND`:

```sql
LINK "users:jane" TO "users:juan" AS "boss"
LINK "users:juan" TO "users:pedro" AS "knows"
FIND THE knows OF THE boss OF users "jane"      -- returns users:pedro
```

### D. PIPE — chain processing stages on a bucket
`PIPE FROM <bucket>` followed by `THEN` stages, each feeding the next.

| Stage | Syntax |
|-------|--------|
| Filter | `THEN WHERE age > 20` |
| Sort | `THEN ARRANGED BY age GOING DOWN` (or `UP`) |
| Limit | `THEN LIMIT 3` |
| Project | `THEN SHOW name, age` |
| Group + aggregate | `THEN GROUP BY city TALLY AS n` |
| Aggregates | `TOTAL OF age AS total_age`, `AVERAGE OF age AS avg_age`, `MIN OF age AS youngest`, `MAX OF age AS oldest` (also `SPREAD`) |

```sql
PIPE FROM users THEN WHERE age > 20 THEN ARRANGED BY age GOING DOWN THEN LIMIT 3 THEN SHOW name, age
```

```sql
PIPE FROM emp THEN WHERE dept = "IT" THEN ARRANGED BY age GOING UP THEN SHOW name
```

```sql
PIPE FROM emp THEN GROUP BY dept TALLY AS n, MIN OF age AS youngest, MAX OF age AS oldest, AVERAGE OF age AS avg
```
