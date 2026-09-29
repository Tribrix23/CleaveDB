import asyncio
import json
import os
import hashlib
from cryptography.fernet import Fernet
import cleavedb3_storage
from cleaveql.lexer import Lexer
from cleaveql.parser import Parser
from cleaveql.interpreter import Interpreter

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

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"[Server] Connection established from {addr}")
    
    authenticated = False
    username = None
    
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
                
                if user_count >= 1:
                    writer.write(b'{"status": "error", "message": "Registration is locked. An account already exists. Only one user is allowed."}\n')
                    await writer.drain()
                    continue

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
                        writer.write(b'{"status": "ok", "message": "Login successful!"}\n')
                        await writer.drain()
                        print(f"[Server] User '{username}' logged in.")
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
    interp = Interpreter(engine)
    user_doc_str = engine.get(f"_auth:{username}")
    user_role = json.loads(user_doc_str).get("role", "dev") if user_doc_str else "dev"
    
    interp.context = {
        "user": username,
        "role": user_role
    }

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
            response = json.dumps(results)
        except Exception as e:
            response = json.dumps([{"status": "error", "message": str(e)}])
        
        writer.write((response + "\n").encode())
        await writer.drain()
    
    print(f"[Server] User '{username}' disconnected.")
    writer.close()

async def main():
    global engine
    engine = cleavedb3_storage.CleaveDB(DB_DIR)
    
    server = await asyncio.start_server(handle_client, HOST, PORT)
    print(f"=========================================")
    print(f"   CleaveDB Server listening on {PORT}")
    print(f"=========================================")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[Server] Shutting down gracefully...')
