import asyncio
SESSION_STORE = {}
import json
import websockets
import os
import sys
import subprocess
import argparse
rate_limit_counters = {}
import hashlib
from cryptography.fernet import Fernet
import cleavedb3_storage
from cleaveql.lexer import Lexer
from cleaveql.parser import Parser
from cleaveql.interpreter import Interpreter
from pysyncobj import SyncObj, replicated_sync, SyncObjConf


HOST = '127.0.0.1'
PORT = 8300
DB_DIR = 'cleavedb_server_data'

# Ensure encryption key exists for Q&A
KEY_FILE = "cleavedb.key"
if not os.path.exists(KEY_FILE):
    with open(KEY_FILE, "wb") as f:
        f.write(Fernet.generate_key())
with open(KEY_FILE, "rb") as f:
    cipher = Fernet(f.read())


GLOBAL_DB = None

class DistributedEngine(SyncObj):
    def __init__(self, selfNodeAddr, otherNodeAddrs, db_dir):
        conf = SyncObjConf(dynamicMembershipChange=True)
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
            return {"username": "dev", "auth_level": "dev"}
            
        user_doc_str = engine.get(f"_auth:{u}")
        if user_doc_str:
            user_data = json.loads(user_doc_str)
            if "dev_hash" in user_data and "dev_salt" in user_data:
                if verify_password(user_data["dev_hash"], user_data["dev_salt"], p):
                    return {"username": u, "auth_level": "dev"}
            if verify_password(user_data["password_hash"], user_data["password_salt"], p):
                return {"username": u, "auth_level": "standard"}
                
        self.send_response(401)
        self.end_headers()
        self.wfile.write(b'{"error": "Invalid credentials"}')
        return None

    def execute_and_respond(self, query, auth_ctx):
        q_upper = query.upper()
        if any(k in q_upper for k in ['POUR', 'CHANGE', 'DRAIN', 'MIGRATE', 'BEGIN']):
            response = dist_engine.execute_write(query, auth_ctx)
        else:
            response = dist_engine.execute_read(query, auth_ctx)
            
        results = response.get("results", [])
        events = response.get("events", [])
        
        # We also need to emit events so WebSockets can hear HTTP mutations!
        if events:
            # We can't easily await inside sync handler, so we create a new loop task
            async def publish_all():
                for event in events:
                    if event.get('event') in ['POUR', 'CHANGE']:
                        view_queue.put(event)
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
        self.end_headers()
        self.wfile.write(json.dumps(results).encode('utf-8'))

    def do_GET(self):
        auth_ctx = self.do_AUTH()
        if not auth_ctx: return
        path = urllib.parse.unquote(self.path)
        parts = [p for p in path.split('/') if p]
        
        if len(parts) >= 3 and parts[0] == 'api':
            bucket = parts[2]
            query = f"FIND {bucket}"
            if len(parts) == 3:
                self.execute_and_respond(query, auth_ctx)
            else:
                doc_id = parts[3]
                response = dist_engine.execute_read(query, auth_ctx)
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
            for v in views:
                body = v.get("body", {})
                if body.get("source") == bucket:
                    view_name = v.get("gid", "").split(":")[-1]
                    group_field = body.get("group_field")
                    sum_field = body.get("sum_field")
                    
                    if group_field in data and sum_field in data:
                        grp = str(data[group_field])
                        try:
                            delta = float(data[sum_field])
                        except ValueError:
                            continue
                            
                        # Micro-transaction bypass
                        tenant_id = event.get("bucket", "").split(".")[0]
                        if "." not in event.get("bucket", ""):
                            tenant_id = None
                            
                        # Prefix the bucket name with tenant_id
                        native_view_bucket = f"{tenant_id}.{view_name}" if tenant_id else view_name
                        
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

    try:
        async for message in websocket:
            try:
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
                                    await websocket.send(json.dumps([{"status": "ok", "message": f"Authenticated as {username} (DEV MODE)"}]))
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
                    
                if 'POUR' in msg_upper or 'CHANGE' in msg_upper or 'DRAIN' in msg_upper or 'MIGRATE' in msg_upper or 'BEGIN' in msg_upper:

                    response = dist_engine.execute_write(message, context)
                else:
                    response = dist_engine.execute_read(message, context)
                
                results = response.get("results", [])
                events = response.get("events", [])
                
                # Dispatch emitted events (vital for WS-initiated queries!)
                for event in events:
                    if event.get('event') in ['POUR', 'CHANGE']:
                        view_queue.put(event)
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
        for t in list(dispatcher.subscribers.keys()):
            dispatcher.unsubscribe(t, websocket)


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
                            # It expired! Hard-delete the actual document and the TTL tracker
                            engine.delete(b.get("target"))
                            engine.delete(t['gid'])
                            print(f"[Cron] TTL Sweeper incinerated expired document: {b.get('target')}")
            except Exception as e:
                print(f"[Cron] Error in TTL cleanup: {e}")

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
                        resp = {"status": "ok", "message": "Login successful! (Dev Superuser Override)", "auth_level": "dev", "username": u}
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
                
            else:
                writer.write(b'{"status": "error", "message": "Unknown action"}\n')
                await writer.drain()
                
        except Exception as e:
            writer.write((json.dumps({"status": "error", "message": str(e)}) + "\n").encode())
            await writer.drain()

    if not authenticated:
        print(f"[Server] Disconnected {addr} (Auth phase)")
        writer.close()
        return

    # 2. Database Query Loop
    user_doc_str = engine.get(f"_auth:{username}")
    user_role = json.loads(user_doc_str).get("role", "dev") if user_doc_str else "dev"
    
    interp = Interpreter(engine, indexing_queue=indexing_queue)
    
    interp.set_context({
        "user_id": f"users:{username}",
        "user": username,
        "role": user_role,
        "auth_level": auth_level
    })

    while True:
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
            if "_req_id" in req:
                req_id = req["_req_id"]
                req_action = req.get("action")
                if req_action == "query":
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

        try:
            client_id = req_id.split('_')[0] if req_id else "0"
            session = SESSION_STORE.get(client_id, {"username": "guest", "auth_level": "none"})
            interp.context["user"] = session["username"]
            interp.context["auth_level"] = session["auth_level"]
            interp.context["tenant_id"] = session.get("tenant_id", session["username"])
            
            stmts = Parser(Lexer(query).tokenize()).parse()
            results = interp.execute(stmts)
            
            if req_id is not None:
                response = json.dumps({"_req_id": req_id, "payload": results})
            else:
                response = json.dumps(results)
        except Exception as e:
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

async def main():
    global dist_engine
    global engine
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8301)
    parser.add_argument('--raft-port', type=int, default=8311)
    parser.add_argument('--peers', type=str, default="")
    parser.add_argument('--data', type=str, default="cleavedb_server_data")
    args = parser.parse_args()
    
    peers = [p.strip() for p in args.peers.split(',')] if args.peers else []
    
    dist_engine = DistributedEngine(f"127.0.0.1:{args.raft_port}", peers, args.data)
    engine = GLOBAL_DB


    threading.Thread(target=view_worker, daemon=True).start()
    threading.Thread(target=vector_worker, daemon=True).start()
    threading.Thread(target=run_http_server, args=(args.port + 2,), daemon=True).start()

    
    server = await asyncio.start_server(handle_client, HOST, args.port - 2)
    ws_server = await websockets.serve(ws_handler, HOST, args.port + 1)
    print(f"=========================================")
    print(f"   CleaveDB TCP Server on {args.port - 2}")
    
    # Automatically boot the Rust Gateway!
    gw_paths = ["edge_gateway.exe", os.path.join("edge_gateway", "target", "release", "edge_gateway.exe")]
    rust_gateway_path = next((p for p in gw_paths if os.path.exists(p)), None)
    
    if rust_gateway_path:
        print(f"   CleaveDB Edge Gateway starting natively on {args.port - 1}")
        subprocess.Popen([rust_gateway_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"   WARNING: Rust Edge Gateway not found. (Did you compile it?)")
        
    print(f"   CleaveDB WS  Server on {args.port + 1}")
    print(f"   CleaveDB Raft Node  on {args.raft_port}")
    print(f"=========================================")

    print(f"   CleaveDB TCP Server listening on {PORT}")
    print(f"   CleaveDB WS  Server listening on 8301")
    print(f"=========================================")
    async with server, ws_server:
        asyncio.create_task(cron_worker())
        await asyncio.gather(server.serve_forever(), ws_server.serve_forever())


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[Server] Shutting down gracefully...')
