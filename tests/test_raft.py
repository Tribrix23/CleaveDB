import asyncio
import websockets
import json
import time
import subprocess
import os

async def test_raft():
    print("Starting 3 nodes...")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    n1 = subprocess.Popen(["python", "cleavedb_server.py", "--port", "8301", "--raft-port", "9001", "--peers", "127.0.0.1:9002,127.0.0.1:9003", "--data", "node1"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    n2 = subprocess.Popen(["python", "cleavedb_server.py", "--port", "8311", "--raft-port", "9002", "--peers", "127.0.0.1:9001,127.0.0.1:9003", "--data", "node2"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    n3 = subprocess.Popen(["python", "cleavedb_server.py", "--port", "8321", "--raft-port", "9003", "--peers", "127.0.0.1:9001,127.0.0.1:9002", "--data", "node3"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    print("Waiting 15 seconds for models to load and Raft cluster to elect a leader...")
    time.sleep(15)
    
    try:
        print("Connecting to Node 1 (Port 8301) and pouring data...")
        async with websockets.connect("ws://127.0.0.1:8301") as ws1:
            query = "POUR INTO users 'raft_test' '{\"name\": \"Consensus Alice\"}'"
            await ws1.send(query)
            res = await ws1.recv()
            print(f"Node 1 Response: {res}")
            
        print("Waiting 2 seconds for Raft replication to sync...")
        time.sleep(2)
        
        print("Connecting to Node 2 (Port 8311) to verify data...")
        async with websockets.connect("ws://127.0.0.1:8311") as ws2:
            query = 'FIND users'
            await ws2.send(query)
            res = await ws2.recv()
            data = json.loads(res)
            found = False
            for node in data[0].get('documents', []):
                if node.get('_id') == "raft_test":
                    print(f"SUCCESS: Node 2 returned the replicated data! {node}")
                    found = True
                    break
            if not found:
                print("FAILED: Node 2 did not have the data.")

        print("Connecting to Node 3 (Port 8321) to verify data...")
        async with websockets.connect("ws://127.0.0.1:8321") as ws3:
            query = 'FIND users'
            await ws3.send(query)
            res = await ws3.recv()
            data = json.loads(res)
            found = False
            for node in data[0].get('documents', []):
                if node.get('_id') == "raft_test":
                    print(f"SUCCESS: Node 3 returned the replicated data! {node}")
                    found = True
                    break
            if not found:
                print("FAILED: Node 3 did not have the data.")
    finally:
        print("Cleaning up nodes...")
        n1.terminate()
        n2.terminate()
        n3.terminate()

if __name__ == '__main__':
    asyncio.run(test_raft())
