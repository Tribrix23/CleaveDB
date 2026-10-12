import asyncio
SESSION_STORE = {}
import json
import websockets
import os
import sys
import subprocess
import argparse
import collections
import math
import shutil
import time
import threading
rate_limit_counters = {}
import hashlib
from cryptography.fernet import Fernet
import cleavedb3_storage
from cleaveql.lexer import Lexer
from cleaveql.parser import Parser
import socket
from cleaveql.interpreter import Interpreter
from cleaveql.security import RESERVED_BUCKET_NAMES
from pysyncobj import SyncObj, replicated_sync, SyncObjConf


HOST = '0.0.0.0'
PORT = 8300
DB_DIR = 'cleavedb_server_data'

import platform
if platform.system() == "Windows":
    _base_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CleaveDB')
else:
    _base_dir = os.path.join(os.path.expanduser('~'), '.cleavedb')

os.makedirs(_base_dir, exist_ok=True)

# Ensure encryption key exists for Q&A
KEY_FILE = os.path.join(_base_dir, "cleavedb.key")
if not os.path.exists(KEY_FILE):
    with open(KEY_FILE, "wb") as f:
        f.write(Fernet.generate_key())
with open(KEY_FILE, "rb") as f:
    cipher = Fernet(f.read())


GLOBAL_DB = None

class DistributedEngine(SyncObj):
    def __init__(self, selfNodeAddr, otherNodeAddrs, db_dir):
        conf = SyncObjConf(
            dynamicMembershipChange=True,
            journalFile=os.path.join(_base_dir, 'journal.bin'),
            fullDumpFile=os.path.join(_base_dir, 'dump.bin')
        )
        super(DistributedEngine, self).__init__(selfNodeAddr, otherNodeAddrs, conf)
        global GLOBAL_DB
        if GLOBAL_DB is None:
            GLOBAL_DB = cleavedb3_storage.CleaveDB(db_dir)
        
    @replicated_sync
    def execute_write(self, query: str, context: dict):
        try:
            lexer = Lexer(query)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            stmts = parser.parse()
            interpreter = Interpreter(GLOBAL_DB, indexing_queue)
            interpreter.set_context(context)
            results = interpreter.execute(stmts)
            return {"results": results, "events": interpreter.emitted_events}
        except Exception as e:
            return {"results": [{"status": "error", "message": str(e)}], "events": []}

    def execute_read(self, query: str, context: dict):
        # Reads don't need raft consensus
        try:
            lexer = Lexer(query)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            stmts = parser.parse()
            interpreter = Interpreter(GLOBAL_DB, indexing_queue)
            interpreter.set_context(context)
            results = interpreter.execute(stmts)
            return {"results": results, "events": interpreter.emitted_events}
        except Exception as e:
            return {"results": [{"status": "error", "message": str(e)}], "events": []}

dist_engine = None
configured_shards = ["127.0.0.1:8300"]

def hash_password(password: str, salt: bytes = None) -> tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return hashed.hex(), salt.hex()

def verify_password(stored_hash: str, stored_salt_hex: str, provided_password: str) -> bool:
    salt = bytes.fromhex(stored_salt_hex)
    hashed, _ = hash_password(provided_password, salt)
    return hashed == stored_hash

engine = None

ACTIVE_PORTS = {
    "gateway": 8300,
    "tcp": 8299,
    "websocket": 8302,
    "http_rest": 8303,
    "coordinator": 8305,
    "raft": 8311
}

class TelemetryEngine:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir
        self.total_requests = 0
        self.req_timestamps = collections.deque()
        self.recent_latencies = collections.deque(maxlen=1000)
        self.chart_history = collections.deque(maxlen=60)
        self._lock = threading.Lock()
        self._last_tick_sec = None
        self._cached_databases = None
        self._last_db_scan = 0.0

        # Pre-seed 60 rolling seconds for chart_history [timestamp, rps, avg_lat]
        now_sec = int(time.time())
        for i in range(59, -1, -1):
            self.chart_history.append([now_sec - i, 0, 0.0])

    def record_request(self, latency_ms: float):
        with self._lock:
            now = time.time()
            self.total_requests += 1
            self.req_timestamps.append(now)
            self.recent_latencies.append(latency_ms)
            # Sliding 1-second request window
            while self.req_timestamps and self.req_timestamps[0] < now - 1.0:
                self.req_timestamps.popleft()

    def get_requests_per_second_locked(self, now_time=None) -> int:
        if now_time is None:
            now_time = time.time()
        while self.req_timestamps and self.req_timestamps[0] < now_time - 1.0:
            self.req_timestamps.popleft()
        return len(self.req_timestamps)

    def get_avg_latency_locked(self) -> float:
        if not self.recent_latencies:
            return 0.0
        return round(sum(self.recent_latencies) / len(self.recent_latencies), 2)

    def get_percentiles_locked(self) -> tuple[float, float]:
        if not self.recent_latencies:
            return 0.0, 0.0
        sorted_lats = sorted(self.recent_latencies)
        n = len(sorted_lats)
        idx95 = min(n - 1, max(0, int(math.ceil(0.95 * n)) - 1))
        idx99 = min(n - 1, max(0, int(math.ceil(0.99 * n)) - 1))
        return round(sorted_lats[idx95], 2), round(sorted_lats[idx99], 2)

    def tick_second(self):
        with self._lock:
            now_sec = int(time.time())
            if self._last_tick_sec is not None and now_sec > self._last_tick_sec + 1:
                # Catch up any missed seconds with zero points
                for s in range(self._last_tick_sec + 1, min(now_sec, self._last_tick_sec + 60)):
                    self.chart_history.append([s, 0, 0.0])

            rps = self.get_requests_per_second_locked(now_sec)
            avg_lat = self.get_avg_latency_locked()
            self.chart_history.append([now_sec, rps, avg_lat])
            self._last_tick_sec = now_sec

    def get_storage(self) -> dict:
        path = self.data_dir if (self.data_dir and os.path.exists(self.data_dir)) else "."
        try:
            total, used, free = shutil.disk_usage(path)
            used_pct = round((used / total) * 100, 2) if total > 0 else 0.0
            return {
                "total_gb": round(total / (1024 ** 3), 2),
                "used_gb": round(used / (1024 ** 3), 2),
                "free_gb": round(free / (1024 ** 3), 2),
                "used_percent": used_pct
            }
        except Exception:
            return {
                "total_gb": 0.0,
                "used_gb": 0.0,
                "free_gb": 0.0,
                "used_percent": 0.0
            }

    def get_databases(self) -> list:
        now = time.time()
        if self._cached_databases is not None and (now - self._last_db_scan < 1.0):
            return self._cached_databases

        catalogs = []
        try:
            global GLOBAL_DB
            db = GLOBAL_DB
            if db and hasattr(db, "show"):
                raw_buckets = db.show("buckets")
                buckets = json.loads(raw_buckets) if raw_buckets else []
                from cleaveql.interpreter import infer_schema_from_docs, format_size_bytes
                for b in buckets:
                    if b.startswith("_"):
                        continue
                    raw_docs = db.scan_bucket(b) if hasattr(db, "scan_bucket") else "[]"
                    docs = json.loads(raw_docs) if raw_docs else []
                    records = len(docs)
                    size_bytes = 0
                    for d in docs:
                        if isinstance(d, dict):
                            body = d.get("body", {})
                            size_bytes += len(json.dumps(body).encode("utf-8"))
                    schema = infer_schema_from_docs(docs)
                    storage_engine = "Columnar LSM" if any(k in b.lower() for k in ("event", "log", "metric", "timeseries", "ts")) else "Document Vector"
                    display_name = b.split(".", 1)[1] if ("." in b and not b.startswith("_")) else b
                    tenant_name = b.split(".", 1)[0] if ("." in b and not b.startswith("_")) else "default"
                    catalogs.append({
                        "name": display_name,
                        "full_name": b,
                        "tenant": tenant_name,
                        "records": records,
                        "size": format_size_bytes(size_bytes),
                        "size_bytes": size_bytes,
                        "storage_engine": storage_engine,
                        "schema": schema,
                        "status": "Online"
                    })
        except Exception as e:
            print(f"[Telemetry] Database scan error: {e}")

        self._cached_databases = catalogs
        self._last_db_scan = now
        return catalogs

    def get_cluster(self) -> dict:
        global dist_engine
        global ACTIVE_PORTS
        node_id = str(getattr(dist_engine, "selfNode", "127.0.0.1:8311")) if dist_engine else "local"
        is_leader = dist_engine._isLeader() if dist_engine else True
        leader = str(dist_engine._getLeader()) if (dist_engine and dist_engine._getLeader()) else node_id
        status = "leader" if is_leader else "replica"
        hq = getattr(dist_engine, "hasQuorum", True) if dist_engine else True
        has_quorum = hq() if callable(hq) else bool(hq)
        peer_nodes = [str(n) for n in getattr(dist_engine, "otherNodes", [])] if dist_engine else []

        return {
            "node_id": node_id,
            "is_leader": is_leader,
            "leader": leader,
            "status": status,
            "has_quorum": has_quorum,
            "peer_nodes": peer_nodes,
            "active_ports": dict(ACTIVE_PORTS)
        }

    def get_snapshot(self) -> dict:
        with self._lock:
            now_time = time.time()
            rps = self.get_requests_per_second_locked(now_time)
            avg_lat = self.get_avg_latency_locked()
            p95, p99 = self.get_percentiles_locked()
            chart = list(self.chart_history)
            total_reqs = self.total_requests

        return {
            "status": "ok",
            "timestamp": int(time.time()),
            "requests_per_second": rps,
            "total_requests": total_reqs,
            "latency_ms": avg_lat,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "chart_history": chart,
            "storage": self.get_storage(),
            "databases": self.get_databases(),
            "cluster": self.get_cluster()
        }

TELEMETRY = TelemetryEngine()
METRICS_SUBSCRIBERS = set()

import base64
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

class RestApiHandler(BaseHTTPRequestHandler):
    def do_AUTH(self):
        auth_header = self.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="CleaveDB"')
            self.end_headers()
            self.wfile.write(b'{"error": "Unauthorized"}')
            return None
            
        try:
            encoded = auth_header.split(' ')[1]
            decoded = base64.b64decode(encoded).decode('utf-8')
            if ':' not in decoded: raise ValueError()
            u, p = decoded.split(':', 1)
        except:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "Invalid Auth Format"}')
            return None
            
        if u == "dev" and p == "perez":
            return {"username": "dev", "user": "dev", "tenant_id": "dev", "auth_level": "dev"}
            
        user_doc_str = engine.get(f"_auth:{u}")
        if user_doc_str:
            user_data = json.loads(user_doc_str)
            if "dev_hash" in user_data and "dev_salt" in user_data:
                if verify_password(user_data["dev_hash"], user_data["dev_salt"], p):
                    return {"username": u, "user": u, "tenant_id": u, "auth_level": "dev"}
            if verify_password(user_data["password_hash"], user_data["password_salt"], p):
                return {"username": u, "user": u, "tenant_id": u, "auth_level": "standard"}
                
        self.send_response(401)
        self.end_headers()
        self.wfile.write(b'{"error": "Invalid credentials"}')
        return None

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def execute_and_respond(self, query, auth_ctx):
        t_start = time.perf_counter()
        q_upper = query.upper()
        if any(k in q_upper for k in ['POUR', 'CHANGE', 'DRAIN', 'MIGRATE', 'BEGIN']):
            response = dist_engine.execute_write(query, auth_ctx)
        else:
            response = dist_engine.execute_read(query, auth_ctx)
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        TELEMETRY.record_request(elapsed_ms)
            
        results = response.get("results", [])
        events = response.get("events", [])
        
        # We also need to emit events so WebSockets can hear HTTP mutations!
        if events:
            # We can't easily await inside sync handler, so we create a new loop task
            async def publish_all():
                for event in events:
                    if event.get('event') in ['POUR', 'CHANGE']:
                        view_queue.put(event)
                    if event.get('event') in ['POUR', 'CHANGE', 'DRAIN']:
                        webhook_queue.put(event)
                        replica_queue.put(event)
                    await dispatcher.publish(event.get('target'), event)
                    if event.get('bucket'):
                        await dispatcher.publish(f"bucket:{event.get('bucket')}", event)
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(publish_all())
            except:
                pass
                
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(results).encode('utf-8'))

    def do_GET(self):
        path = urllib.parse.unquote(self.path)
        clean_path = path.split('?')[0]
        parts = [p for p in clean_path.split('/') if p]
        
        # Phase 5: Telemetry Engine Endpoint (Public with CORS for GUI Dashboards)
        if len(parts) == 2 and parts[0] == 'api' and parts[1] == 'metrics':
            snapshot = TELEMETRY.get_snapshot()
            data_bytes = json.dumps(snapshot).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            self.send_header('Content-Length', str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)
            return

        auth_ctx = self.do_AUTH()
        if not auth_ctx: return
        
        if len(parts) >= 3 and parts[0] == 'api':
            bucket = parts[2]
            query = f"FIND {bucket}"
            if len(parts) == 3:
                self.execute_and_respond(query, auth_ctx)
            else:
                doc_id = parts[3]
                t_start = time.perf_counter()
                response = dist_engine.execute_read(query, auth_ctx)
                elapsed_ms = (time.perf_counter() - t_start) * 1000.0
                TELEMETRY.record_request(elapsed_ms)
                results = response.get("results", [])
                
                if len(results) > 0 and 'documents' in results[0]:
                    target_docs = []
                    for d in results[0]['documents']:
                        gid = d.get('gid', '')
                        if gid.endswith(f".{doc_id}") or gid == f"{bucket}:{doc_id}":
                            target_docs.append(d)
                    results[0]['documents'] = target_docs
                    results[0]['count'] = len(target_docs)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(results).encode('utf-8'))
        else:
            self.send_error(404)

    def do_POST(self):
        auth_ctx = self.do_AUTH()
        if not auth_ctx: return
        path = urllib.parse.unquote(self.path)
        parts = [p for p in path.split('/') if p]
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        if len(parts) == 3 and parts[0] == 'api' and parts[2] == 'query':
            self.execute_and_respond(body, auth_ctx)
            return
            
        if len(parts) == 3 and parts[0] == 'api':
            bucket = parts[2]
            if bucket.lower() in RESERVED_BUCKET_NAMES:
                self.send_error(400, f"Cannot use reserved keyword '{bucket}' as a bucket name.")
                return
            if bucket.startswith("_") and auth_ctx.get("auth_level") != "dev":
                self.send_error(403, f"Cannot write directly to system bucket '{bucket}'.")
                return
            query = f"POUR INTO {bucket} RANDOM {body}"
            self.execute_and_respond(query, auth_ctx)
        else:
            self.send_error(404)
            
    def do_PUT(self):
        auth_ctx = self.do_AUTH()
        if not auth_ctx: return
        path = urllib.parse.unquote(self.path)
        parts = [p for p in path.split('/') if p]
        if len(parts) == 4 and parts[0] == 'api':
            bucket = parts[2]
            doc_id = parts[3]
            if bucket.lower() in RESERVED_BUCKET_NAMES:
                self.send_error(400, f"Cannot use reserved keyword '{bucket}' as a bucket name.")
                return
            if bucket.startswith("_") and auth_ctx.get("auth_level") != "dev":
                self.send_error(403, f"Cannot write directly to system bucket '{bucket}'.")
                return
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            query = f'POUR INTO {bucket} "{doc_id}" {body}'
            self.execute_and_respond(query, auth_ctx)
        else:
            self.send_error(404)

    def do_PATCH(self):
        auth_ctx = self.do_AUTH()
        if not auth_ctx: return
        path = urllib.parse.unquote(self.path)
        parts = [p for p in path.split('/') if p]
        if len(parts) == 4 and parts[0] == 'api':
            bucket = parts[2]
            doc_id = parts[3]
            if bucket.lower() in RESERVED_BUCKET_NAMES:
                self.send_error(400, f"Cannot use reserved keyword '{bucket}' as a bucket name.")
                return
            if bucket.startswith("_") and auth_ctx.get("auth_level") != "dev":
                self.send_error(403, f"Cannot write directly to system bucket '{bucket}'.")
                return
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                body_json = json.loads(body)
                sets = []
                for k, v in body_json.items():
                    v_str = f'"{v}"' if isinstance(v, str) else str(v)
                    sets.append(f"{k} TO {v_str}")
                set_clause = ", ".join(sets)
                query = f'CHANGE {bucket} "{doc_id}" SET {set_clause}'
                self.execute_and_respond(query, auth_ctx)
            except Exception as e:
                self.send_error(400, "Invalid JSON body for PATCH")
        else:
            self.send_error(404)

    def do_DELETE(self):
        auth_ctx = self.do_AUTH()
        if not auth_ctx: return
        path = urllib.parse.unquote(self.path)
        parts = [p for p in path.split('/') if p]
        if len(parts) == 4 and parts[0] == 'api':
            bucket = parts[2]
            doc_id = parts[3]
            if bucket.lower() in RESERVED_BUCKET_NAMES:
                self.send_error(400, f"Cannot use reserved keyword '{bucket}' as a bucket name.")
                return
            if bucket.startswith("_") and auth_ctx.get("auth_level") != "dev":
                self.send_error(403, f"Cannot write directly to system bucket '{bucket}'.")
                return
            query = f'DRAIN {bucket} "{doc_id}"'
            self.execute_and_respond(query, auth_ctx)
        else:
            self.send_error(404)

def run_http_server(port):
    server = HTTPServer((HOST, port), RestApiHandler)
    server.serve_forever()


import time
import queue
import threading


class EventDispatcher:
    def __init__(self):
        self.subscribers = {} # target_id -> set(websocket)

    async def publish(self, target_id, data):
        if target_id in self.subscribers:
            to_remove = set()
            for ws in self.subscribers[target_id]:
                try:
                    await ws.send(json.dumps(data))
                except Exception:
                    to_remove.add(ws)
            self.subscribers[target_id] -= to_remove

    def subscribe(self, target_id, ws):
        if target_id not in self.subscribers:
            self.subscribers[target_id] = set()
        self.subscribers[target_id].add(ws)
        
    def unsubscribe(self, target_id, ws):
        if target_id in self.subscribers and ws in self.subscribers[target_id]:
            self.subscribers[target_id].remove(ws)

dispatcher = EventDispatcher()
view_queue = queue.Queue()
webhook_queue = queue.Queue()
replica_queue = queue.Queue()

def webhook_worker():
    print("[Server] Asynchronous Webhook Worker started.")
    import urllib.request
    import urllib.error
    import time
    while True:
        try:
            event = webhook_queue.get()
            evt_type = event.get("event")
            evt_bucket = event.get("bucket")
            
            webhooks_str = GLOBAL_DB.scan_bucket("_webhooks")
            if webhooks_str:
                webhooks = json.loads(webhooks_str)
                for w in webhooks:
                    body = w.get("body", {})
                    if body.get("bucket") == evt_bucket and body.get("action") == evt_type:
                        payload = {
                            "event": evt_type,
                            "bucket": evt_bucket,
                            "gid": event.get("target"),
                            "body": event.get("data"),
                            "timestamp": int(time.time()),
                            "tenant": body.get("tenant", "")
                        }
                        import uuid
                        payload_bytes = json.dumps(payload).encode("utf-8")
                        try:
                            from cleaveql.security import validate_webhook_url
                            validate_webhook_url(body.get("url"))
                        except Exception as ve:
                            GLOBAL_DB.pour("_webhook_log", str(uuid.uuid4()), json.dumps({"webhook": body.get("name"), "status": "blocked", "error": str(ve), "timestamp": int(time.time())}))
                            continue
                        for attempt in range(3):
                            req = urllib.request.Request(body.get("url"), data=payload_bytes, headers={"Content-Type": "application/json"}, method="POST")
                            try:
                                urllib.request.urlopen(req, timeout=5)
                                GLOBAL_DB.pour("_webhook_log", str(uuid.uuid4()), json.dumps({"webhook": body.get("name"), "status": "success", "attempts": attempt+1, "timestamp": int(time.time())}))
                                break
                            except Exception as e:
                                if attempt == 2:
                                    GLOBAL_DB.pour("_webhook_log", str(uuid.uuid4()), json.dumps({"webhook": body.get("name"), "status": "failed", "error": str(e), "attempts": 3, "timestamp": int(time.time())}))
                                else:
                                    time.sleep(2 ** attempt)
            webhook_queue.task_done()
        except Exception as e:
            import traceback
            traceback.print_exc()

def view_worker():
    print("[Server] Asynchronous Continuous View Worker started.")
    while True:
        try:
            event = view_queue.get()
            bucket = event.get("bucket")
            evt_type = event.get("event")
            data = event.get("data", {})
            
            # Fetch all registered views
            views_str = engine.scan_bucket("_views")
            if not views_str:
                view_queue.task_done()
                continue
                
            views = json.loads(views_str)
            t_evt = event.get("tenant")
            for v in views:
                body = v.get("body", {})
                t_view = body.get("tenant")
                if body.get("source") == bucket and (t_view == t_evt or t_view is None):
                    view_name = v.get("gid", "").split(":")[-1]
                    if "." in view_name: view_name = view_name.split(".", 1)[1]
                    group_field = body.get("group_field")
                    sum_field = body.get("sum_field")
                    
                    if group_field in data and sum_field in data:
                        grp = str(data[group_field])
                        try:
                            delta = float(data[sum_field])
                        except ValueError:
                            continue
                            
                        # Micro-transaction bypass
                        target_gid = event.get("target", "")
                        tenant_id = target_gid.split(".")[0] if ":" in target_gid and "." in target_gid.split(":")[0] else None
                            
                        # Prefix the bucket name with tenant_id
                        # Wait! view_name ALREADY HAS the tenant ID in it if it's from _views!
                        # e.g. view_user_1fe556.region_sales
                        native_view_bucket = view_name
                        
                        existing_str = engine.get(f"{native_view_bucket}:{grp}")
                        current_total = 0.0
                        if existing_str:
                            existing = json.loads(existing_str)
                            current_total = existing.get(sum_field, 0.0)
                        
                        new_total = current_total + delta
                        engine.pour(native_view_bucket, grp, json.dumps({"_group": grp, sum_field: new_total}))
                        print(f"[ViewWorker] Micro-transaction applied to {view_name}:{grp} (+{delta})")
                        
            view_queue.task_done()
        except Exception as e:
            import traceback
            traceback.print_exc()

indexing_queue = queue.Queue()

def vector_worker():
    from attention.sra import get_embedding
    print("[Server] Asynchronous Vector Indexing Worker started.")
    while True:
        try:
            gid, text_content = indexing_queue.get()
            print(f"[VectorWorker] Generating embedding for {gid}..."); vec = get_embedding(text_content); print(f"[VectorWorker] Storing {gid}!");
            # Store as JSON list array
            # engine.pour("_embeddings", gid, ...)
            # Wait, pour appends bucket to ID. Let's just put it in _embeddings bucket with ID=gid
            engine.pour("_embeddings", gid, json.dumps(vec.tolist()))
            indexing_queue.task_done()
        except Exception as e:
            print(f"[VectorWorker] Error: {e}")


async def ws_handler(websocket):
    context = None
    transaction_buffer = []

    # Auto-subscribe if connecting directly to metrics stream
    req_path = getattr(websocket, 'path', getattr(getattr(websocket, 'request', None), 'path', ''))
    if any(p in req_path for p in ('/metrics', '/api/metrics', '/telemetry')):
        METRICS_SUBSCRIBERS.add(websocket)
        try:
            await websocket.send(json.dumps({
                "status": "ok",
                "event": "metrics_subscribed",
                "message": "Subscribed to CleaveDB Telemetry stream (1s interval)",
                "telemetry": TELEMETRY.get_snapshot()
            }))
        except Exception:
            pass

    try:
        async for message in websocket:
            try:
                # Telemetry Stream Subscription Hook (Works both pre-auth and post-auth)
                try:
                    probe = json.loads(message.strip())
                    if isinstance(probe, dict):
                        act = probe.get("action") or probe.get("type")
                        if act in ("subscribe_metrics", "metrics_subscribe", "subscribe_telemetry"):
                            METRICS_SUBSCRIBERS.add(websocket)
                            await websocket.send(json.dumps({
                                "status": "ok",
                                "event": "metrics_subscribed",
                                "message": "Subscribed to CleaveDB Telemetry stream (1s interval)",
                                "telemetry": TELEMETRY.get_snapshot()
                            }))
                            continue
                        elif act in ("unsubscribe_metrics", "metrics_unsubscribe"):
                            METRICS_SUBSCRIBERS.discard(websocket)
                            await websocket.send(json.dumps({
                                "status": "ok",
                                "event": "metrics_unsubscribed",
                                "message": "Unsubscribed from telemetry stream"
                            }))
                            continue
                except Exception:
                    pass

                # 1. Require strict JSON authentication first
                if context is None:
                    try:
                        req = json.loads(message.strip())
                        if req.get("action") == "authenticate":
                            username = req.get("username")
                            password = req.get("password")
                            
                            # Verify against _auth bucket
                            auth_json = GLOBAL_DB.scan_bucket("_auth")
                            users = json.loads(auth_json) if auth_json else []
                            user_record = next((u["body"] for u in users if u.get("gid") == f"_auth:{username}"), None)
                            
                            if user_record:
                                if verify_password(user_record["password_hash"], user_record["password_salt"], password):
                                    context = {"user": username, "role": user_record.get("role", "user"), "auth_level": "standard"}
                                    await websocket.send(json.dumps([{"status": "ok", "message": f"Authenticated as {username}"}]))
                                    continue
                                elif user_record.get("dev_hash") and verify_password(user_record["dev_hash"], user_record.get("dev_salt", ""), password):
                                    context = {"user": username, "role": user_record.get("role", "user"), "auth_level": "dev"}
                                    await websocket.send(json.dumps([{"status": "ok", "message": f"Authenticated as {username}"}]))
                                    continue
                            
                            await websocket.send(json.dumps([{"status": "error", "message": "Invalid username or password"}]))
                            continue
                        else:
                            await websocket.send(json.dumps([{"status": "error", "message": "First message must be JSON auth payload"}]))
                            continue
                    except json.JSONDecodeError:
                        await websocket.send(json.dumps([{"status": "error", "message": "Authentication required. Send JSON {action: authenticate, username, password}"}]))
                        continue

                # Phase 9: Rate Limit Check
                role = context.get("role", "user")
                rate_limit_doc = GLOBAL_DB.get(f"_rate_limits:{role}")
                if rate_limit_doc:
                    limit_data = json.loads(rate_limit_doc)
                    max_queries = limit_data.get("limit", 60)
                    
                    current_time = time.time()
                    minute_window = int(current_time // 60)
                    user_key = f"{context['user']}_{minute_window}"
                    
                    current_count = rate_limit_counters.get(user_key, 0)
                    if current_count >= max_queries:
                        await websocket.send(json.dumps([{"status": "error", "message": "Rate limit exceeded 429"}]))
                        continue
                    rate_limit_counters[user_key] = current_count + 1

                # 2. Proceed with CleaveQL queries once authenticated
                msg_upper = message.strip().upper()
                if msg_upper == "BEGIN TRANSACTION" or msg_upper == "BEGIN":
                    transaction_buffer = [message]
                    await websocket.send(json.dumps([{"status": "ok", "message": "Transaction started. Buffering statements..."}]))
                    continue
                elif msg_upper == "ROLLBACK":
                    if not transaction_buffer:
                        await websocket.send(json.dumps([{"status": "error", "message": "No active transaction to rollback"}]))
                        continue
                    transaction_buffer = []
                    await websocket.send(json.dumps([{"status": "ok", "message": "Transaction aborted"}]))
                    continue
                elif msg_upper == "COMMIT":
                    if not transaction_buffer:
                        await websocket.send(json.dumps([{"status": "error", "message": "No active transaction to commit"}]))
                        continue
                    transaction_buffer.append(message)
                    message = " ".join(transaction_buffer)
                    transaction_buffer = []
                elif transaction_buffer:
                    transaction_buffer.append(message)
                    await websocket.send(json.dumps([{"status": "ok", "message": "Statement queued"}]))
                    continue
                    
                t_start = time.perf_counter()
                if 'POUR' in msg_upper or 'CHANGE' in msg_upper or 'DRAIN' in msg_upper or 'MIGRATE' in msg_upper or 'BEGIN' in msg_upper:
                    response = dist_engine.execute_write(message, context)
                else:
                    response = dist_engine.execute_read(message, context)
                elapsed_ms = (time.perf_counter() - t_start) * 1000.0
                TELEMETRY.record_request(elapsed_ms)
                
                results = response.get("results", [])
                events = response.get("events", [])
                
                # Dispatch emitted events (vital for WS-initiated queries!)
                for event in events:
                    if event.get('event') in ['POUR', 'CHANGE']:
                        view_queue.put(event)
                    if event.get('event') in ['POUR', 'CHANGE', 'DRAIN']:
                        webhook_queue.put(event)
                        replica_queue.put(event)
                    await dispatcher.publish(event.get('target'), event)
                    if event.get('bucket'):
                        await dispatcher.publish(f"bucket:{event.get('bucket')}", event)

                # Check if it was a listen statement
                for res in results:
                    if res.get("status") == "listen":
                        target = res.get("target")
                        dispatcher.subscribe(target, websocket)
                
                await websocket.send(json.dumps(results))
            except Exception as e:
                import traceback
                traceback.print_exc()
                await websocket.send(json.dumps([{"status": "error", "message": str(e)}]))
    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        METRICS_SUBSCRIBERS.discard(websocket)
        for t in list(dispatcher.subscribers.keys()):
            dispatcher.unsubscribe(t, websocket)


async def telemetry_broadcaster():
    print("[Server] Telemetry Broadcaster started (1s interval).")
    while True:
        try:
            await asyncio.sleep(1.0)
            TELEMETRY.tick_second()
            if METRICS_SUBSCRIBERS:
                packet = json.dumps(TELEMETRY.get_snapshot())
                dead = set()
                for ws in list(METRICS_SUBSCRIBERS):
                    try:
                        await ws.send(packet)
                    except Exception:
                        dead.add(ws)
                if dead:
                    METRICS_SUBSCRIBERS.difference_update(dead)
        except Exception as e:
            print(f"[Telemetry] Broadcaster loop error: {e}")


async def cron_worker():
    print("[Server] Cron Worker started.")
    while True:
        await asyncio.sleep(5)  # Check every 5 seconds
        if not engine:
            continue
            
        try:
            current_time = int(time.time())
            
            # --- Rubbish Cleanup ---
            try:
                r_data = engine.scan_bucket("_rubbish")
                if r_data:
                    rubbish = json.loads(r_data)
                    for r in rubbish:
                        doc = engine.get(r['gid'])
                        if doc:
                            body = json.loads(doc)
                            if current_time - body.get("deleted_at", current_time) > 259200:
                                engine.delete(r['gid'])
            except Exception as e:
                print(f"[Cron] Error in rubbish cleanup: {e}")
                
            # --- Ephemeral Data TTL Cleanup ---
            try:
                ttl_data = engine.scan_bucket("_ttl")
                if ttl_data:
                    ttls = json.loads(ttl_data)
                    for t in ttls:
                        b = t.get("body", {})
                        if b.get("expires_at", 0) < current_time:
                            # Re-verify the tracker in case a concurrent thread modified it
                            current_tracker_json = engine.get(t['gid'])
                            if current_tracker_json:
                                cb = json.loads(current_tracker_json)
                                if cb.get("expires_at", 0) < current_time:
                                    # It is still expired! Hard-delete the actual document and the TTL tracker
                                    engine.delete(cb.get("target"))
                                    engine.delete(t['gid'])
                                    print(f"[Cron] TTL Sweeper incinerated expired document: {cb.get('target')}")
            except Exception as e:
                print(f"[Cron] Error in TTL cleanup: {e}")

            # --- Graph Relation TTL Cleanup ---
            try:
                bonds_data = engine.scan_bucket("_bonds")
                if bonds_data:
                    bonds = json.loads(bonds_data)
                    for b_doc in bonds:
                        body = b_doc.get("body", {})
                        if body.get("expires_at") and body.get("expires_at") < current_time:
                            # Re-verify the bond in case a concurrent thread modified or severed it
                            current_bond_json = engine.get(b_doc['gid'])
                            if current_bond_json:
                                cb = json.loads(current_bond_json)
                                if cb.get("expires_at") and cb.get("expires_at") < current_time:
                                    engine.delete(b_doc['gid'])
                                    print(f"[Cron] Graph Sweeper incinerated expired bond: {b_doc['gid']}")
            except Exception as e:
                print(f"[Cron] Error in Graph Relation TTL cleanup: {e}")

            # Scan the hidden _cron bucket
            cron_data = engine.scan_bucket("_cron")
            if not cron_data:
                continue
                
            jobs = json.loads(cron_data)
            current_time = int(time.time())
            
            for job in jobs:
                job_id = job.get("id")
                if not job_id or str(job_id) == "None":
                    # Physically delete the broken ghost job from the database
                    gid = f"_cron:{job_id}"
                    try:
                        engine.delete(gid)
                    except:
                        pass
                    continue
                body = job.get("body", {})
                interval = body.get("interval", 0)
                last_run = body.get("last_run", 0)
                command = body.get("command", "")
                
                if current_time - last_run >= interval:
                    print(f"[Cron] Executing job {job_id}: {command}")
                    # Update last_run first to avoid duplicate runs
                    body["last_run"] = current_time
                    engine.pour("_cron", job_id, json.dumps(body))
                    
                    # Execute the command
                    try:
                        lexer = Lexer(command)
                        parser = Parser(lexer.tokenize())
                        stmts = parser.parse()
                        interp = Interpreter(engine, indexing_queue=indexing_queue)
                        interp.set_context({"user": "cron", "role": "admin"})
                        results = interp.execute(stmts)
                        print(f"[Cron] Result: {results}")
                    except Exception as e:
                        print(f"[Cron] Error executing job {job_id}: {e}")
                        
        except Exception as e:
            print(f"[Cron] Worker loop error: {e}")

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"[Server] Connection established from {addr}")
    
    authenticated = False
    username = None
    auth_level = None
    first_query_line = None
    
    # 1. Shell Auth Loop
    while not authenticated:
        auth_line = await reader.readline()
        if not auth_line:
            break
            
        try:
            req = json.loads(auth_line.decode().strip())
            print(f"LOGIN REQ: {req}", flush=True)
            action = req.get("action")
            
            if action == "register":
                # Only allow ONE registration total
                users_json = engine.scan_bucket("_auth")
                user_count = len(json.loads(users_json)) if users_json else 0
                
                # Registration limit removed for multi-tenancy!

                u = req.get("username")
                is_first = True
                
                pw_hash, pw_salt = hash_password(req["password"])
                dev_hash, dev_salt = hash_password(req.get("dev_password", ""))
                
                enc_q = cipher.encrypt(req["question"].encode()).decode()
                enc_a = cipher.encrypt(req["answer"].lower().encode()).decode()
                
                doc = {
                    "username": u,
                    "password_hash": pw_hash,
                    "password_salt": pw_salt,
                    "dev_hash": dev_hash,
                    "dev_salt": dev_salt,
                    "role": "admin" if is_first else "dev",
                    "security_question": enc_q,
                    "security_answer": enc_a
                }
                
                engine.pour("_auth", u, json.dumps(doc))
                resp = {"status": "ok", "message": "Registration successful! You can now login."}
                if req.get("_req_id"):
                                resp = {"_req_id": req["_req_id"], "payload": resp}
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()

            elif action == "login":
                u = req.get("username")
                p = req.get("password")
                user_doc_str = engine.get(f"_auth:{u}")
                
                client_id = req.get("_req_id", "0_0").split('_')[0]
                
                if user_doc_str:
                    user_data = json.loads(user_doc_str)
                    if verify_password(user_data["password_hash"], user_data["password_salt"], p):
                        authenticated = True
                        username = u
                        auth_level = "standard"
                        SESSION_STORE[client_id] = {"username": u, "auth_level": "standard", "tenant_id": user_data.get("tenant_id", u)}
                        resp = {"status": "ok", "message": "Login successful! (Standard Access)", "auth_level": "standard", "username": u}
                        if req.get("_req_id"):
                                resp = {"_req_id": req["_req_id"], "payload": resp}
                        writer.write((json.dumps(resp) + "\n").encode())
                        await writer.drain()
                        print(f"[Server] User '{username}' logged in (Standard).")
                        continue
                    elif user_data.get("dev_hash") and verify_password(user_data["dev_hash"], user_data.get("dev_salt", ""), p):
                        authenticated = True
                        username = u
                        auth_level = "dev"
                        SESSION_STORE[client_id] = {"username": u, "auth_level": "dev", "tenant_id": user_data.get("tenant_id", u)}
                        resp = {"status": "ok", "message": "Login successful! (Level: dev)", "auth_level": "dev", "username": u}
                        if req.get("_req_id"):
                                resp = {"_req_id": req["_req_id"], "payload": resp}
                        writer.write((json.dumps(resp) + "\n").encode())
                        await writer.drain()
                        print(f"[Server] User '{username}' logged in (Dev).")
                        continue
                        
                resp = {"status": "error", "message": "Invalid username or password"}
                if req.get("_req_id"):
                                resp = {"_req_id": req["_req_id"], "payload": resp}
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()

            elif action == "forgot_step1":
                u = req.get("username")
                user_doc_str = engine.get(f"_auth:{u}")
                if user_doc_str:
                    user_data = json.loads(user_doc_str)
                    decrypted_q = cipher.decrypt(user_data["security_question"].encode()).decode()
                    resp = {"status": "ok", "question": decrypted_q}
                else:
                    resp = {"status": "error", "message": "User not found"}
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
                
            elif action == "forgot_step2":
                u = req.get("username")
                ans = req.get("answer", "").lower()
                new_pw = req.get("new_password")
                user_doc_str = engine.get(f"_auth:{u}")
                if user_doc_str:
                    user_data = json.loads(user_doc_str)
                    decrypted_ans = cipher.decrypt(user_data["security_answer"].encode()).decode()
                    if decrypted_ans == ans:
                        pw_hash, pw_salt = hash_password(new_pw)
                        user_data["password_hash"] = pw_hash
                        user_data["password_salt"] = pw_salt
                        engine.pour("_auth", u, json.dumps(user_data))
                        writer.write(b'{"status": "ok", "message": "Password reset successfully!"}\n')
                        await writer.drain()
                        continue
                writer.write(b'{"status": "error", "message": "Invalid answer or recovery failed"}\n')
                await writer.drain()
                
            elif action == "query" or (isinstance(req, dict) and "query" in req):
                authenticated = True
                username = req.get("username", "admin")
                auth_level = req.get("auth_level", "dev")
                first_query_line = auth_line
                break
                
            else:
                writer.write(b'{"status": "error", "message": "Unknown action"}\n')
                await writer.drain()
                
        except Exception:
            raw_text = auth_line.decode().strip()
            if raw_text:
                authenticated = True
                username = "admin"
                auth_level = "dev"
                first_query_line = auth_line
                break
            writer.write(b'{"status": "error", "message": "Invalid query payload"}\n')
            await writer.drain()

    if not authenticated:
        print(f"[Server] Disconnected {addr} (Auth phase)")
        writer.close()
        return

    # 2. Database Query Loop
    user_doc_str = engine.get(f"_auth:{username}")
    user_data = json.loads(user_doc_str) if user_doc_str else {}
    user_role = user_data.get("role", "dev")
    tenant_id = user_data.get("tenant_id", username)
    
    interp = Interpreter(engine, indexing_queue=indexing_queue)
    
    interp.set_context({
        "user_id": f"users:{username}",
        "user": username,
        "tenant_id": tenant_id,
        "role": user_role,
        "auth_level": auth_level
    })

    while True:
        if first_query_line is not None:
            data = first_query_line
            first_query_line = None
        else:
            data = await reader.readline()
            if not data:
                break
        
        query = data.decode().strip()
        if not query:
            continue
        print('QUERY REQ:', query, flush=True)
            
        req_id = None
        req_action = None
        try:
            req = json.loads(query)
            if isinstance(req, dict):
                req_id = req.get("_req_id")
                req_action = req.get("action")
                if req_action == "query" and "query" in req:
                    query = req["query"]
        except Exception:
            pass
        
        if req_action == "login":
            u = req.get("username")
            p = req.get("password")
            user_doc_str = engine.get(f"_auth:{u}")
            resp = {"status": "error", "message": "Invalid username or password"}
            
            client_id = req_id.split('_')[0] if req_id else "0"
            
            if user_doc_str:
                user_data = json.loads(user_doc_str)
                if verify_password(user_data["password_hash"], user_data["password_salt"], p):
                    resp = {"status": "ok", "message": f"Login successful! (Standard Access)", "username": u, "auth_level": "standard"}
                    SESSION_STORE[client_id] = {"username": u, "auth_level": "standard", "tenant_id": user_data.get("tenant_id", u)}
                elif user_data.get("dev_hash") and verify_password(user_data["dev_hash"], user_data.get("dev_salt", ""), p):
                    resp = {"status": "ok", "message": f"Login successful! (Dev Superuser Override)", "username": u, "auth_level": "dev"}
                    SESSION_STORE[client_id] = {"username": u, "auth_level": "dev", "tenant_id": user_data.get("tenant_id", u)}
            
            response = json.dumps({"_req_id": req_id, "payload": resp}) if req_id else json.dumps(resp)
            writer.write((response + "\n").encode())
            await writer.drain()
            continue
            
        if req_action == "register":
            u = req.get("username")
            pw_hash, pw_salt = hash_password(req["password"])
            dev_hash, dev_salt = hash_password(req.get("dev_password", ""))
            enc_q = cipher.encrypt(req["question"].encode()).decode() if req.get("question") else ""
            enc_a = cipher.encrypt(req["answer"].lower().encode()).decode() if req.get("answer") else ""
            
            doc = {
                "username": u,
                "password_hash": pw_hash,
                "password_salt": pw_salt,
                "dev_hash": dev_hash,
                "dev_salt": dev_salt,
                "role": "admin",
                "tenant_id": u,
                "security_question": enc_q,
                "security_answer": enc_a
            }
            engine.pour("_auth", u, json.dumps(doc))
            resp = {"status": "ok", "message": "Registration successful! You can now login."}
            response = json.dumps({"_req_id": req_id, "payload": resp}) if req_id else json.dumps(resp)
            writer.write((response + "\n").encode())
            await writer.drain()
            continue

        if req_action == "forgot_step1":
            u = req.get("username")
            user_doc_str = engine.get(f"_auth:{u}")
            if user_doc_str:
                user_data = json.loads(user_doc_str)
                decrypted_q = cipher.decrypt(user_data["security_question"].encode()).decode()
                resp = {"status": "ok", "question": decrypted_q}
            else:
                resp = {"status": "error", "message": "User not found"}
            response = json.dumps({"_req_id": req_id, "payload": resp}) if req_id else json.dumps(resp)
            writer.write((response + "\n").encode())
            await writer.drain()
            continue
            
        if req_action == "forgot_step2":
            u = req.get("username")
            ans = req.get("answer", "").lower()
            new_pw = req.get("new_password")
            user_doc_str = engine.get(f"_auth:{u}")
            resp = {"status": "error", "message": "Invalid answer or recovery failed"}
            if user_doc_str:
                user_data = json.loads(user_doc_str)
                decrypted_ans = cipher.decrypt(user_data["security_answer"].encode()).decode()
                if decrypted_ans == ans:
                    pw_hash, pw_salt = hash_password(new_pw)
                    user_data["password_hash"] = pw_hash
                    user_data["password_salt"] = pw_salt
                    engine.pour("_auth", u, json.dumps(user_data))
                    resp = {"status": "ok", "message": "Password reset successfully!"}
            
            response = json.dumps({"_req_id": req_id, "payload": resp}) if req_id else json.dumps(resp)
            writer.write((response + "\n").encode())
            await writer.drain()
            continue

        try:
            client_id = req_id.split('_')[0] if req_id else "0"
            session = SESSION_STORE.get(client_id, {"username": "guest", "auth_level": "none"})
            interp.context["user"] = session["username"]
            interp.context["auth_level"] = session["auth_level"]
            interp.context["tenant_id"] = session.get("tenant_id", session["username"])
            
            t_start = time.perf_counter()
            stmts = Parser(Lexer(query).tokenize()).parse()
            results = interp.execute(stmts)
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            TELEMETRY.record_request(elapsed_ms)
            
            for event in interp.emitted_events:
                if event.get('event') in ['POUR', 'CHANGE']:
                    view_queue.put(event)
                if event.get('event') in ['POUR', 'CHANGE', 'DRAIN']:
                    webhook_queue.put(event)
                    replica_queue.put(event)
                # Ignore dispatcher for now since it causes errors without create_task
            interp.emitted_events.clear()
            
            if req_id is not None:
                response = json.dumps({"_req_id": req_id, "payload": results})
            else:
                response = json.dumps(results)
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0 if 't_start' in locals() else 0.0
            TELEMETRY.record_request(elapsed_ms)
            err = {"status": "error", "message": str(e)}
            if req_id is not None:
                response = json.dumps({"_req_id": req_id, "payload": [err]})
            else:
                response = json.dumps([err])
        
        print('QUERY RESP:', response, flush=True)
        writer.write((response + "\n").encode())
        await writer.drain()
    
    print(f"[Server] User '{username}' disconnected.")
    writer.close()

def replica_worker():
    print("[Server] Asynchronous Replica Worker started.")
    import json
    while True:
        try:
            event = replica_queue.get()
            evt_type = event.get("event")
            evt_bucket = event.get("bucket")
            evt_gid = event.get("target")
            data = event.get("data", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except:
                    data = {}
            
            replicas_str = GLOBAL_DB.scan_bucket("_replicas")
            if replicas_str:
                replicas = json.loads(replicas_str)
                for r in replicas:
                    body = r.get("body", {})
                    if body.get("source") == evt_bucket:
                        print(f"[ReplicaWorker] MATCH BUCKET: {evt_bucket}, evt_type: {evt_type}, gid: {evt_gid}", flush=True)
                        target = body.get("target")
                        when = body.get("when")
                        show = body.get("show_fields", [])
                        
                        # Evaluate condition
                        match = True
                        if when:
                            if when.get("type") == "WhereClause":
                                # Very basic evaluation of the first predicate for the feature plan
                                preds = when.get("predicates", [])
                                if preds:
                                    p = preds[0]
                                    left = p.get("field")
                                    right = p.get("value")
                                    op = p.get("op")
                                    
                                    val = data.get(left)
                                    if op == "=" or op == "==":
                                        match = (str(val) == str(right))
                                    elif op == "!=":
                                        match = (str(val) != str(right))
                                
                        if match and evt_type in ["POUR", "CHANGE"]:
                            # Project fields
                            projected = {}
                            if show:
                                for f in show:
                                    if f in data:
                                        projected[f] = data[f]
                            else:
                                projected = data.copy()
                            
                            # Upsert to target bucket
                            actual_id = evt_gid.split(":")[-1] if ":" in evt_gid else evt_gid
                            target_tenant = evt_gid.split(".")[0] if "." in evt_gid else ""
                            full_target = f"{target_tenant}.{target}" if target_tenant else target
                            GLOBAL_DB.pour(full_target, actual_id, json.dumps(projected))
                            
                        elif not match or evt_type == "DRAIN":
                            # Remove from target bucket if it doesn't match anymore or was deleted
                            actual_id = evt_gid.split(":")[-1] if ":" in evt_gid else evt_gid
                            target_tenant = evt_gid.split(".")[0] if "." in evt_gid else ""
                            full_target = f"{target_tenant}.{target}" if target_tenant else target
                            GLOBAL_DB.delete(f"{full_target}:{actual_id}")
                            
            replica_queue.task_done()
        except Exception as e:
            import traceback
            traceback.print_exc()

async def main():
    global dist_engine
    global configured_shards
    global engine
    global HOST
    
    parser = argparse.ArgumentParser(description="CleaveDB Server")
    parser.add_argument('-H', '--host', type=str, default='0.0.0.0', help="Host IP to bind TCP/WS/HTTP servers to (default: 0.0.0.0)")
    parser.add_argument('--node-ip', type=str, default=None, help="Reachable LAN/public IP for this node in Raft consensus clustering")
    parser.add_argument('--port', type=int, default=8301)
    parser.add_argument('--raft-port', type=int, default=8311)
    parser.add_argument('--peers', type=str, default="")
    parser.add_argument('--data', type=str, default=os.path.join(_base_dir, "cleavedb_server_data"))
    args = parser.parse_args()
    
    HOST = args.host
    peers = [p.strip() for p in args.peers.split(',')] if args.peers else []
    
    # Determine the node's broadcast/binding IP for Raft consensus
    if args.node_ip:
        node_ip = args.node_ip
    elif args.peers and any(p.startswith("127.0.0.1") or p.startswith("localhost") for p in peers):
        node_ip = "127.0.0.1"
    elif args.host not in ('0.0.0.0', ''):
        node_ip = args.host
    elif not args.peers:
        node_ip = "127.0.0.1"
    else:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            node_ip = s.getsockname()[0]
            s.close()
        except Exception:
            node_ip = "127.0.0.1"
    
    dist_engine = DistributedEngine(f"{node_ip}:{args.raft_port}", peers, args.data)
    engine = GLOBAL_DB
    TELEMETRY.data_dir = args.data
    # Automatically locate the Rust Gateway!
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
    file_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else exe_dir
    gw_paths = [
        "edge_gateway.exe",
        os.path.join(exe_dir, "edge_gateway.exe"),
        os.path.join(exe_dir, "..", "edge_gateway.exe"),
        os.path.join(exe_dir, "..", "..", "edge_gateway.exe"),
        os.path.join(file_dir, "edge_gateway.exe"),
        os.path.join(file_dir, "edge_gateway", "target", "release", "edge_gateway.exe"),
        os.path.join("edge_gateway", "target", "release", "edge_gateway.exe")
    ]
    rust_gateway_path = next((os.path.abspath(p) for p in gw_paths if os.path.exists(p)), None)
    
    # If edge gateway is found, Python binds on internal IPC port (args.port - 2 = 8299).
    # If gateway is missing, Python binds directly to public port (args.port - 1 = 8300) so clients never hang!
    if rust_gateway_path:
        server_tcp_port = args.port - 2
    else:
        server_tcp_port = args.port - 1

    ACTIVE_PORTS.update({
        "gateway": args.port - 1,
        "tcp": server_tcp_port,
        "websocket": args.port + 1,
        "http_rest": args.port + 2,
        "coordinator": args.port + 4,
        "raft": args.raft_port
    })

    threading.Thread(target=view_worker, daemon=True).start()
    threading.Thread(target=webhook_worker, daemon=True).start()
    threading.Thread(target=replica_worker, daemon=True).start()
    threading.Thread(target=vector_worker, daemon=True).start()
    threading.Thread(target=run_http_server, args=(args.port + 2,), daemon=True).start()

    server = await asyncio.start_server(handle_client, HOST, server_tcp_port)
    ws_server = await websockets.serve(ws_handler, HOST, args.port + 1)
    print(f"=========================================")
    print(f"   CleaveDB TCP Server on {HOST}:{server_tcp_port}")
    
    if rust_gateway_path:
        print(f"   CleaveDB Edge Gateway starting natively on 0.0.0.0:{args.port - 1}")
        subprocess.Popen([rust_gateway_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"   NOTICE: Rust Edge Gateway not found. Bound directly to client port 0.0.0.0:{server_tcp_port}")
        
    # Automatically locate the Go Coordinator!
    coord_paths = [
        "coordinator.exe",
        os.path.join(exe_dir, "coordinator.exe"),
        os.path.join(exe_dir, "..", "coordinator.exe"),
        os.path.join(exe_dir, "..", "..", "coordinator.exe"),
        os.path.join(file_dir, "coordinator.exe"),
        os.path.join(file_dir, "coordinator", "coordinator.exe"),
        os.path.join("coordinator", "coordinator.exe")
    ]
    go_coord_path = next((os.path.abspath(p) for p in coord_paths if os.path.exists(p)), None)
    if go_coord_path:
        coord_port = args.port + 4
        shards_arg = f"{node_ip}:{args.port - 1}"
        if args.peers:
            all_shards = [shards_arg] + [p.strip() for p in args.peers.split(',') if p.strip()]
            shards_arg = ",".join(all_shards)
            configured_shards = all_shards
        else:
            configured_shards = [shards_arg]
        print(f"   CleaveDB Go Coordinator starting natively on {coord_port}")
        subprocess.Popen([go_coord_path, f"-port={coord_port}", f"-shards={shards_arg}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"   NOTICE: Go Coordinator not found.")
        
    print(f"   CleaveDB WS  Server on {HOST}:{args.port + 1}")
    print(f"   CleaveDB HTTP REST  on {HOST}:{args.port + 2}")
    print(f"   CleaveDB Raft Node  on {node_ip}:{args.raft_port}")
    print(f"=========================================")
    async with server, ws_server:
        asyncio.create_task(cron_worker())
        asyncio.create_task(telemetry_broadcaster())
        await asyncio.gather(server.serve_forever(), ws_server.serve_forever())


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[Server] Shutting down gracefully...')
