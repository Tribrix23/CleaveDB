with open("cleave_cli.py", "r", encoding="utf-8") as f:
    text = f.read()

import re

old_loop = """                print("Booting up database engine... (This can take up to 16 seconds for the AI Transformer)")
                
                # Retry loop for up to 16 seconds
                connected = False
                for _ in range(16):
                    time.sleep(1)
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.connect((args.host, args.port))
                        connected = True
                        break
                    except ConnectionRefusedError:
                        continue
                
                if not connected:
                    print("Auto-start failed: Timed out waiting for database engine.")
                    time.sleep(5)
                    sys.exit(1)"""

new_loop = """                print("Booting up database engine... (This can take up to 30 seconds for the AI Transformer and SIMD engine)")
                
                # Retry loop for up to 30 seconds
                connected = False
                for _ in range(30):
                    time.sleep(1)
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.connect((args.host, args.port))
                        connected = True
                        break
                    except Exception:
                        continue
                
                if not connected:
                    print("Auto-start failed: Timed out waiting for database engine after 30 seconds.")
                    time.sleep(5)
                    sys.exit(1)"""

text = text.replace(old_loop, new_loop)

with open("cleave_cli.py", "w", encoding="utf-8") as f:
    f.write(text)
print("Updated cleave_cli.py timeout and exception handling")
