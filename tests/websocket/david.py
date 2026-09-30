import asyncio
import websockets
import json
import uuid
import sys
import time
import msvcrt

async def chat_client(username):
    uri = "ws://127.0.0.1:8301"
    try:
        async with websockets.connect(uri) as websocket:
            print(f"=================================================")
            print(f" ?? Welcome to CleaveDB Real-Time Chat, {username}!")
            print(f"=================================================")
            
            await websocket.send('LISTEN TO chat')
            await websocket.send('LISTEN TO chat_typing')
            
            typing_users = set()
            current_input = []
            is_indicator_showing = [False]
            
            def clear_ui():
                sys.stdout.write('\r\033[K')
                if is_indicator_showing[0]:
                    sys.stdout.write('\033[1A\033[K')
                    is_indicator_showing[0] = False

            def redraw_ui():
                clear_ui()
                if typing_users:
                    typists = ", ".join(typing_users)
                    sys.stdout.write(f"\033[90m{typists} is typing...\033[0m\n")
                    is_indicator_showing[0] = True
                sys.stdout.write(f"[{username}]: " + "".join(current_input))
                sys.stdout.flush()
            
            # --- TYPING TIMEOUT TASK ---
            last_typed_time = [0]
            is_typing_state = [False]
            
            async def typing_timeout_loop():
                while True:
                    await asyncio.sleep(1)
                    if is_typing_state[0] and (time.time() - last_typed_time[0] > 3.0):
                        is_typing_state[0] = False
                        try:
                            await websocket.send(f'POUR INTO chat_typing "{username}" {{"is_typing": false}}')
                        except:
                            break
            
            asyncio.create_task(typing_timeout_loop())
            # ---------------------------
            
            async def listen_loop():
                while True:
                    try:
                        message = await websocket.recv()
                        data = json.loads(message)
                        
                        if isinstance(data, dict) and data.get("event") in ["POUR", "CHANGE"]:
                            bucket = data.get("bucket")
                            doc_data = data.get("data", {})
                            
                            if bucket == "chat":
                                sender = doc_data.get("sender")
                                text = doc_data.get("text")
                                if sender != username:
                                    clear_ui()
                                    if sender in typing_users:
                                        typing_users.remove(sender)
                                        
                                    print(f"[{sender}]: {text}")
                                    redraw_ui()
                                    
                            elif bucket == "chat_typing":
                                target = data.get("target", "")
                                sender = target.split(".")[-1]
                                
                                if sender != username:
                                    is_typing = doc_data.get("is_typing", False)
                                    changed = False
                                    if is_typing and sender not in typing_users:
                                        typing_users.add(sender)
                                        changed = True
                                    elif not is_typing and sender in typing_users:
                                        typing_users.remove(sender)
                                        changed = True
                                        
                                    if changed:
                                        redraw_ui()
                                        
                    except websockets.exceptions.ConnectionClosed:
                        print("\n[Server disconnected]")
                        break
                    except Exception:
                        pass
                        
            asyncio.create_task(listen_loop())
            
            while True:
                current_input.clear()
                is_typing_state[0] = False
                
                redraw_ui()
                
                while True:
                    while not msvcrt.kbhit():
                        await asyncio.sleep(0.05)
                        
                    ch = msvcrt.getch()
                    
                    if ch in (b'\r', b'\n'):
                        clear_ui()
                        text = "".join(current_input).strip()
                        if text:
                            print(f"[{username}]: {text}")
                            
                        if is_typing_state[0]:
                            await websocket.send(f'POUR INTO chat_typing "{username}" {{"is_typing": false}}')
                            
                        if text:
                            if text.lower() in ['exit', 'quit']:
                                return
                            msg_id = str(uuid.uuid4())[:6]
                            query = f'POUR INTO chat "{msg_id}" {{"sender": "{username}", "text": "{text}"}}'
                            await websocket.send(query)
                        break
                    elif ch == b'\x08': # Backspace
                        if current_input:
                            current_input.pop()
                            if not current_input and is_typing_state[0]:
                                is_typing_state[0] = False
                                await websocket.send(f'POUR INTO chat_typing "{username}" {{"is_typing": false}}')
                            redraw_ui()
                    elif ch == b'\x03': # Ctrl+C
                        return
                    else:
                        try:
                            decoded = ch.decode('utf-8')
                            if decoded.isprintable():
                                current_input.append(decoded)
                                last_typed_time[0] = time.time()
                                
                                if not is_typing_state[0]:
                                    is_typing_state[0] = True
                                    await websocket.send(f'POUR INTO chat_typing "{username}" {{"is_typing": true}}')
                                redraw_ui()
                        except UnicodeDecodeError:
                            pass
                
    except ConnectionRefusedError:
        print("Could not connect to CleaveDB!")

import sys
import time

if __name__ == "__main__":
    name = "David" if "david" in sys.argv[0].lower() else "Jessy"
    asyncio.run(chat_client(name))
