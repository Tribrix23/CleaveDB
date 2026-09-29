import socket
import json
import sys
import getpass
import argparse

SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What is your mother's maiden name?",
    "What city were you born in?",
    "What is your favorite book?",
    "What was the make of your first car?"
]

def do_register(f):
    print("\n--- Register New User ---")
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.")
        return
        
    dev_password = getpass.getpass("Dev Password (superuser override): ")
    
    print("\nSelect a security question for account recovery:")
    for i, q in enumerate(SECURITY_QUESTIONS):
        print(f"[{i+1}] {q}")
    
    try:
        q_idx = int(input("Choice (1-5): "))
        if not (1 <= q_idx <= len(SECURITY_QUESTIONS)):
            raise ValueError()
        question = SECURITY_QUESTIONS[q_idx - 1]
    except ValueError:
        print("Invalid choice.")
        return
        
    print(f"\nQuestion: {question}")
    answer = input("Answer: ").strip()
    
    req = {
        "action": "register",
        "username": username,
        "password": password,
        "dev_password": dev_password,
        "question": question,
        "answer": answer
    }
    
    f.write(json.dumps(req) + "\n")
    f.flush()
    
    resp_str = f.readline().strip()
    if not resp_str:
        print("Server disconnected.")
        sys.exit(1)
        
    resp = json.loads(resp_str)
    if resp.get("status") == "ok":
        print(f"\n[+] {resp.get('message')}\n")
    else:
        print(f"\n[-] Error: {resp.get('message')}\n")

def do_login(f):
    print("\n--- Login ---")
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    
    req = {
        "action": "login",
        "username": username,
        "password": password
    }
    
    f.write(json.dumps(req) + "\n")
    f.flush()
    
    resp_str = f.readline().strip()
    if not resp_str:
        print("Server disconnected.")
        sys.exit(1)
        
    resp = json.loads(resp_str)
    if resp.get("status") == "ok":
        print(f"\n[+] {resp.get('message')}\n")
        return True
    else:
        print(f"\n[-] Error: {resp.get('message')}\n")
        return False

def do_forgot(f):
    print("\n--- Forgot Password ---")
    username = input("Username: ").strip()
    
    f.write(json.dumps({"action": "forgot_step1", "username": username}) + "\n")
    f.flush()
    
    resp_str = f.readline().strip()
    if not resp_str:
        print("Server disconnected.")
        sys.exit(1)
        
    resp = json.loads(resp_str)
    if resp.get("status") == "error":
        print(f"\n[-] Error: {resp.get('message')}\n")
        return
        
    print(f"\nSecurity Question: {resp['question']}")
    answer = input("Answer: ").strip()
    new_pw = getpass.getpass("Enter new password: ")
    
    req = {
        "action": "forgot_step2",
        "username": username,
        "answer": answer,
        "new_password": new_pw
    }
    f.write(json.dumps(req) + "\n")
    f.flush()
    
    final_resp_str = f.readline().strip()
    final_resp = json.loads(final_resp_str)
    if final_resp.get("status") == "ok":
        print(f"\n[+] {final_resp.get('message')}\n")
    else:
        print(f"\n[-] Recovery failed: {final_resp.get('message')}\n")


def main():
    parser = argparse.ArgumentParser(description="CleaveDB Interactive Shell")
    parser.add_argument("-H", "--host", default="127.0.0.1", help="Server host IP")
    parser.add_argument("-p", "--port", type=int, default=8300, help="Server port number")
    args = parser.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((args.host, args.port))
    except ConnectionRefusedError:
        print(f"Error: Could not connect to CleaveDB server at {args.host}:{args.port}")
        print("Is the server running?")
        sys.exit(1)

    f = s.makefile('rw')
    
    print("========================================")
    print("        Welcome to CleaveDB Shell       ")
    print("========================================")
    print("Not logged in. Type a command to begin.")
    print("  login    - Log into an existing account")
    print("  register - Create a new user account")
    print("  forgot   - Recover a lost password")
    print("  exit     - Close the shell")
    
    authenticated = False
    while not authenticated:
        try:
            cmd = input("\ncleavedb-auth> ").strip().lower()
            if cmd in ['exit', 'quit']:
                s.close()
                sys.exit(0)
            elif cmd == 'register':
                do_register(f)
            elif cmd == 'login':
                authenticated = do_login(f)
            elif cmd == 'forgot':
                do_forgot(f)
            elif cmd:
                print("Unknown command. Please type 'login', 'register', 'forgot', or 'exit'.")
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            sys.exit(0)
            
    print("========================================")
    print("Type your CleaveQL commands.")
    print("Type 'exit' or 'quit' to close.")
    print("========================================")
    while True:
        try:
            cmd = input("cleavedb> ").strip()
            if cmd.lower() in ['exit', 'quit']:
                break
            if not cmd:
                continue
            
            f.write(cmd + "\n")
            f.flush()
            
            response_str = f.readline().strip()
            if not response_str:
                print("Server closed connection.")
                break
                
            try:
                response_json = json.loads(response_str)
                print(json.dumps(response_json, indent=2))
            except:
                print(response_str)
                
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break
    
    s.close()
    print("Goodbye.")

if __name__ == "__main__":
    main()
