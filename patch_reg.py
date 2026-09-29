with open('cleavedb_server.py', 'r') as f:
    content = f.read()

orig = """            if action == "register":
                u = req.get("username")
                existing = engine.get(f"_auth:{u}")
                if existing:
                    writer.write(b'{"status": "error", "message": "Username already exists"}\\n')
                    await writer.drain()
                    continue
                    
                # First user registered gets 'admin' role automatically
                users_json = engine.scan_bucket("_auth")
                is_first = len(json.loads(users_json)) == 0 if users_json else True"""

new = """            if action == "register":
                # Only allow ONE registration total
                users_json = engine.scan_bucket("_auth")
                user_count = len(json.loads(users_json)) if users_json else 0
                
                if user_count >= 1:
                    writer.write(b'{"status": "error", "message": "Registration is locked. An account already exists. Only one user is allowed."}\\n')
                    await writer.drain()
                    continue

                u = req.get("username")
                is_first = True"""

content = content.replace(orig, new)

with open('cleavedb_server.py', 'w') as f:
    f.write(content)
