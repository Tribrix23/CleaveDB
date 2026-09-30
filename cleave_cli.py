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


HELP_TEXT = """
================================================================================
  CleaveDB 3.0 Manual (CleaveQL) - Complete Comprehensive Reference
================================================================================

1. WRITE & UPDATE (Mutations)
  POUR INTO <bucket> "<id>" {json}           - Insert/upsert document (use RANDOM for auto-ID).
  POUR MANY INTO <bucket> [{json}, {json}]   - Bulk insert multiple documents.
  CHANGE <id> IN <bucket> TO <field> = <val> - Update specific fields.
  DRAIN <bucket> "<id>"                      - Move document to _rubbish bin.
  DRAIN <bucket> BEFORE "<date>"             - Bulk move old documents to _rubbish.
  SALVAGE "<id>" FROM _rubbish               - Restore specific document from rubbish.
  SALVAGE EVERYTHING FROM _rubbish           - Restore all documents.
  INCINERATE "<id>" FROM _rubbish            - Permanently delete document.
  INCINERATE EVERYTHING FROM _rubbish        - Empty the trash bin.

2. READ & SEARCH (SCOOP Engine)
  FIND <bucket>                           - (Alias: SCOOP EVERYTHING FROM <bucket>)
  FIND <bucket> [Modifiers...]            - Native English document querying.
  
  [Modifiers - chainable in any order]
  ... WHERE <field> <op> <value>          - Evaluate expressions (<, >, =, AND, OR).
  ... WHOSE <field> IS <value>            - Exact field match filter.
  ... WITH <field1>, <field2>             - Native Joins (Alias: INCLUDE).
  ... SORTED BY <field> [DESC|ASC]        - Sort results (Alias: ARRANGED BY).
  ... LIMIT <n>                           - Restrict number of results.
  ... SHOW <field1>, <field2>             - Return specific fields (Alias: YIELD).
  ... MEANING "<text>"                    - AI Vector Semantic Search.
  ... MENTIONING "<text>"                 - Full Text Search.

3. GRAPH RELATIONS & TRAVERSAL (15D BONDS)
  BOND "<source_id>" TO "<target_id>" AS "<label>" - Create a directional relationship.
  FIND "<label>" OF "<source_id>"                  - Query direct relationships.
  TRACE "<label>" FROM "<source_id>"               - Traverse deep nested graph links.

4. AUTOMATION & TIME TRAVEL
  TIME TRAVEL <bucket> AS OF "<date>"     - Read historical state (requires Versioned bucket).
  SET CRON "<schedule>" DO <command>      - Register scheduled background tasks.
  SHOW CRON                               - List running background jobs.

5. ANALYTICS & AGGREGATION
  SCOOP THE TALLY OF <bucket>             - Total document count.
  SCOOP ONLY UNIQUE <field> FROM <bucket> - Returns distinct field values.
  SCOOP TOTAL <field> GROUPED BY <field> FROM <bucket> - Grouped summation.
  DISTILL <bucket>                        - Advanced pipeline aggregation.

4. GRAPH RELATIONS (15D Bonds)
  BOND "<id1>" TO "<id2>" AS "<label>"    - Create relationship.
    [Modifiers]: MUTUAL, CASCADE, EXCLUSIVELY, CONFIDENCE <float>, 
                 AFFINITY <float>, EXPIRES IN <seconds>, CONDITION <field> = <val>
  SCOOP THE <label> OF <bucket> "<id>"    - Traversal (e.g. SCOOP THE friend OF users "u1").
  SCOOP RELATED "<label>" FROM "<id>"     - Returns detailed metadata about bonds.
  SUGGEST BONDS                           - AI suggests missing logical relationships.
  FOLLOW ...                              - Legacy graph API traversal.

5. SECURITY (DLS & Masking)
  MASK <field> IN <bucket>                - Redact field (***) from standard users.
  POLICY <name> ON <bucket> TO <action> WHERE <field> = <val> - Row-level security.
  SET CONTEXT <key> TO "<value>"          - Set session state (e.g. SET CONTEXT role TO "admin").

6. INFRASTRUCTURE & SCHEDULING
  SHAPE BUCKET <bucket>                   - Configures a bucket (TTL, Max Docs).
  SHAPE PROJECTION ...                    - Defines a virtual materialized view.
  INDEX <field> IN <bucket>               - Builds B+Tree index for O(log N) lookups.
  SCHEDULE EVERY <seconds> SECONDS "<cmd>"- Registers a background Cron daemon.

7. DIAGNOSTICS & METADATA
  SHOW BUCKETS                            - List all active buckets.
  DESCRIBE <bucket>                       - Display statistics for a specific bucket.
  HEAL ALL  (or HEAL BUCKET <bucket>)     - Reclaim WAL space & defragment buffer pool.
  PEER EXPLAIN "<query>"                  - Print internal Rust execution plan.
================================================================================
"""

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
        return resp
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

    while True:
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

        auth_data = False
        while not auth_data:
            try:
                cmd = input("\ncleavedb-auth> ").strip().lower()
                if cmd in ['exit', 'quit']:
                    s.close()
                    sys.exit(0)
                elif cmd == 'register':
                    do_register(f)
                elif cmd == 'login':
                    auth_data = do_login(f)
                elif cmd == 'forgot':
                    do_forgot(f)
                elif cmd:
                    print("Unknown command. Please type 'login', 'register', 'forgot', or 'exit'.")
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                sys.exit(0)
                
        print("========================================")
        print("Type your CleaveQL commands.")
        print("Type 'logout' to switch users, or 'exit' to close.")
        print("========================================")
        
        RED = "\033[91m"
        RESET = "\033[0m"
        
        if auth_data.get("auth_level") == "dev":
            prompt = f"{RED}root@cleavedb{RESET}> "
        else:
            prompt = f"{auth_data.get('username', 'user')}@cleavedb> "
            
        while True:
            try:
                cmd = input(prompt).strip()
                if cmd.lower() in ['exit', 'quit']:
                    s.close()
                    sys.exit(0)
                if cmd.lower() == 'logout':
                    print("Logged out successfully.\n")
                    s.close()
                    break
                if cmd.lower() in ['?', 'help']:
                    print(HELP_TEXT)
                    continue
                if cmd.lower() in ['cls', 'clear']:
                    import os
                    os.system('cls' if os.name == 'nt' else 'clear')
                    continue
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
                s.close()
                sys.exit(0)
                
    s.close()
    print("Goodbye.")

if __name__ == "__main__":
    main()
