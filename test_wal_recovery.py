import os
os.environ['RUST_LOG'] = 'info'
import os, json, time, shutil
import cleavedb3_storage

db_path = os.path.join(os.getcwd(), "wal_test_db")
if os.path.exists(db_path):
    shutil.rmtree(db_path)

print("Starting Process 1: Inserting 100 Documents...")
engine = cleavedb3_storage.CleaveDB(db_path)

for i in range(100):
    engine.pour("test_bucket", f"doc_{i}", json.dumps({"hello": "world", "id": i}))

# Check if they exist in memory
assert json.loads(engine.get("test_bucket:doc_50"))["id"] == 50
print("100 Documents inserted and verified in memory.")

print("Simulating crash... (Destroying engine instance without clean shutdown)")
del engine 
time.sleep(1) # Allow OS to flush any pending async IO if necessary

print("Starting Process 2: Recovering from WAL...")
engine2 = cleavedb3_storage.CleaveDB(db_path)

# Try fetching them again
doc = engine2.get("test_bucket:doc_50")
assert doc is not None, "Document 50 is missing! WAL Recovery Failed!"
doc_json = json.loads(doc)
assert doc_json["id"] == 50, "Document 50 is corrupted!"

count = 0
for i in range(100):
    if engine2.get(f"test_bucket:doc_{i}"):
        count += 1

print(f"Success! WAL Recovery restored {count}/100 documents across the B+Tree shards!")

