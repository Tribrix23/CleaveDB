import asyncio
import json
import websockets
import os
import sys
import argparse
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


class DistributedEngine(SyncObj):
    def __init__(self, selfNodeAddr, otherNodeAddrs, db_dir):
        conf = SyncObjConf(dynamicMembershipChange=True)
        super(DistributedEngine, self).__init__(selfNodeAddr, otherNodeAddrs, conf)
        self.local_db = cleavedb3_storage.CleaveDB(db_dir)
        
    @replicated_sync
    def execute_write(self, query: str, context: dict):
        try:
            lexer = Lexer(query)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            stmts = parser.parse()
            interpreter = Interpreter(self.local_db, indexing_queue)
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
            interpreter = Interpreter(self.local_db, indexing_queue)
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
                            auth_json = dist_engine.local_db.scan_bucket("_auth")
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

                # 2. Proceed with CleaveQL queries once authenticated
                if 'POUR' in message.upper() or 'CHANGE' in message.upper() or 'DRAIN' in message.upper():
                    response = dist_engine.execute_write(message, context)
                else:
                    response = dist_engine.execute_read(message, context)
                
                results = response.get("results", [])
                events = response.get("events", [])
                
                # Dispatch emitted events (vital for WS-initiated queries!)
                for event in events:
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
                writer.write(b'{"status": "ok", "message": "Registration successful! You can now login."}\n')
                await writer.drain()

            elif action == "login":
                u = req.get("username")
                p = req.get("password")
                user_doc_str = engine.get(f"_auth:{u}")
                if user_doc_str:
                    user_data = json.loads(user_doc_str)
                    if verify_password(user_data["password_hash"], user_data["password_salt"], p):
                        authenticated = True
                        username = u
                        auth_level = "standard"
                        writer.write(f'{{"status": "ok", "message": "Login successful! (Standard Access)", "auth_level": "standard", "username": "{u}"}}\n'.encode())
                        await writer.drain()
                        print(f"[Server] User '{username}' logged in (Standard).")
                        continue
                    elif user_data.get("dev_hash") and verify_password(user_data["dev_hash"], user_data.get("dev_salt", ""), p):
                        authenticated = True
                        username = u
                        auth_level = "dev"
                        writer.write(f'{{"status": "ok", "message": "Login successful! (Dev Superuser Override)", "auth_level": "dev", "username": "{u}"}}\n'.encode())
                        await writer.drain()
                        print(f"[Server] User '{username}' logged in (Dev).")
                        continue
                        
                writer.write(b'{"status": "error", "message": "Invalid username or password"}\n')
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
        
        try:
            stmts = Parser(Lexer(query).tokenize()).parse()
            results = interp.execute(stmts)
            
            # Dispatch emitted events
            # events not currently supported in Raft cluster mode
            
            response = json.dumps(results)
        except Exception as e:
            response = json.dumps([{"status": "error", "message": str(e)}])
        
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
    engine = dist_engine.local_db

    threading.Thread(target=vector_worker, daemon=True).start()
    
    server = await asyncio.start_server(handle_client, HOST, args.port - 1)
    ws_server = await websockets.serve(ws_handler, HOST, args.port)
    print(f"=========================================")
    print(f"   CleaveDB TCP Server on {args.port - 1}")
    print(f"   CleaveDB WS  Server on {args.port}")
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
