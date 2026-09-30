import asyncio
import websockets
import json

async def run_test():
    uri = "ws://127.0.0.1:8301"
    async with websockets.connect(uri) as ws:
        print("==========================================")
        print("  CleaveDB Ephemeral TTL Test")
        print("==========================================")
        
        print("\n1. Injecting session token with 3 second TTL...")
        await ws.send('POUR INTO sessions "my_token" {"user": "Alice"} EXPIRES IN 3 DAYS')
        res = await ws.recv()
        print("Response:", res)
        
        print("\n2. Finding the document immediately...")
        await ws.send('FIND sessions WHERE user = "Alice"')
        res_str = await ws.recv()
        res = json.loads(res_str)
        if res and isinstance(res, list) and len(res) > 0 and 'documents' in res[0]:
            docs = res[0]['documents']
            if len(docs) > 0:
                doc = docs[0]['body']
                print("Found! Document body:", doc)
                print("Notice the injected '_expires_at' field:", doc.get('_expires_at'))
            else:
                print("Not found! Documents array is empty.")
        else:
            print("Not found!", res)
            
        print("\n3. Testing short TTL... pouring again with 3 SECONDS...")
        await ws.send('POUR INTO sessions "my_token" {"user": "Alice"} EXPIRES IN 3 SECONDS')
        await ws.recv()
            
        print("\n4. Waiting 5 seconds for the server's background cron worker to sweep it...")
        for i in range(5):
            print(f"   Tick... {i+1}")
            await asyncio.sleep(1)
            
        print("\n5. Finding the document again...")
        await ws.send('FIND sessions WHERE user = "Alice"')
        res_str = await ws.recv()
        res = json.loads(res_str)
        if res and isinstance(res, list) and len(res) > 0 and 'documents' in res[0]:
            docs = res[0]['documents']
            if len(docs) > 0:
                print("Found:", docs[0])
            else:
                print("[] -> The document was successfully incinerated by the background sweeper!")
        else:
            print("Empty result:", res)

asyncio.run(run_test())
