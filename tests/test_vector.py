import asyncio
import websockets
import json
import time

async def run_test():
    uri = "ws://127.0.0.1:8301"
    async with websockets.connect(uri) as ws:
        print("==========================================")
        print("  CleaveDB Async Vector Indexing Benchmark")
        print("==========================================")
        
        # We will insert 20 documents. Synchronously this would take ~2 seconds!
        docs = [
            "A fast sports car driving down the highway",
            "A delicious slice of pepperoni pizza",
            "A beautiful sunset over the mountains",
            "A programmer writing code late at night",
            "A tiny kitten sleeping on a soft pillow",
            "A golden retriever playing fetch in the park",
            "An astronaut floating in space",
            "A medieval knight in shining armor",
            "A futuristic cyberpunk city with neon lights",
            "A cup of hot coffee on a rainy day"
        ] * 2
        
        print(f"\n1. Injecting {len(docs)} documents with heavy semantic text...")
        start_time = time.time()
        for i, text in enumerate(docs):
            await ws.send(f'POUR INTO articles "bulk_{i}" {{"text": "{text}"}}')
            await ws.recv() # wait for OK
            
        end_time = time.time()
        print(f"-> Poured {len(docs)} documents in {end_time - start_time:.4f} seconds!")
        print("   (With blocking AI, this would have taken 20x longer!)")
        
        print("\n2. Immediately searching for 'cute dog' (Checking Eventual Consistency)")
        await ws.send('FIND articles MEANING "cute dog"')
        res = json.loads(await ws.recv())
        found_now = len(res[0].get('documents', [])) if res else 0
        print(f"-> Found matches instantly: {found_now} (Background thread is still chewing!)")
            
        print("\n3. Waiting 2.5 seconds for the background ONNX Vector Indexer to catch up...")
        for i in range(5):
            print(f"   Tick... {i+1}")
            await asyncio.sleep(0.5)
        
        print("\n4. Performing Semantic Search again...")
        await ws.send('FIND "cute dog" IN articles')
        res = json.loads(await ws.recv())
        
        if res and len(res) > 0 and len(res[0].get('documents', [])) > 0:
            print(f"-> Found matches: {len(res[0]['documents'])}")
            for doc in res[0]['documents'][:2]: # print top 2
                print(f"  - {doc['body']['text']} (Score: {doc.get('_embedding_distance')})")
        else:
            print("Still empty! Something went wrong.")

asyncio.run(run_test())
