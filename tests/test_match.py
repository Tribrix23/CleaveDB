import asyncio
import websockets
import json

async def run_test():
    uri = "ws://127.0.0.1:8301"
    async with websockets.connect(uri) as ws:
        print("==========================================")
        print("  CleaveDB Subgraph English Pattern Test")
        print("==========================================")
        
        query = 'FIND PATTERN IN users AS u LINKED VIA "works_in" TO departments AS d LINKED VIA "located_in" TO cities AS c WHERE d.name = "AI"'
        print("   Query:", query)
        await ws.send(query)
        res_str = await ws.recv()
        res = json.loads(res_str)
        
        # In MatchStmt, it returns a JSON string, so if res[0] is a string, parse it again!
        if isinstance(res[0], str):
            res = json.loads(res[0])
            
        if res and res[0].get('status') == 'ok':
            print("\n-> Match found! Paths:")
            for path in res[0]['paths']:
                print(f"  User: {path['u']['body']['name']} -> Dept: {path['d']['body']['name']} -> City: {path['c']['body']['name']}")
                break # Just print one to avoid duplicates
        else:
            print("\nFailed:", res)

asyncio.run(run_test())
