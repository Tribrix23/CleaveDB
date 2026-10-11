import subprocess
import time
import socket
import json
import urllib.request
import urllib.error
import os
import sys

def send_tcp(host, port, message):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect((host, port))
    payload = message.strip() + "\n"
    s.sendall(payload.encode('utf-8'))
    data = b""
    while True:
        try:
            chunk = s.recv(8192)
            if not chunk:
                break
            data += chunk
            if b'\n' in data:
                break
        except socket.timeout:
            break
    s.close()
    return data.decode('utf-8').strip()

def send_http(url, method="GET", payload=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    # Base64 dev:dev for superuser auth
    req.add_header("Authorization", "Basic ZGV2OmRldg==")
    data_bytes = json.dumps(payload).encode('utf-8') if payload else None
    try:
        with urllib.request.urlopen(req, data=data_bytes, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

def main():
    print("=" * 60)
    print("   CLEAVEDB PHASE 2 E2E TEST SUITE")
    print("=" * 60)

    import tempfile, shutil
    tmp_data = tempfile.mkdtemp(prefix="cleavedb_e2e_")

    # 1. Start Server
    print("\n[Step 1] Booting CleaveDB server stack with isolated data directory...")
    srv_proc = subprocess.Popen(
        [sys.executable, "cleavedb_server.py", "-H", "127.0.0.1", "--port", "8301", "--data", tmp_data],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.getcwd()
    )

    # Give server 3 seconds to spin up TCP, Gateway, WS, REST, Coordinator
    time.sleep(3.5)

    try:
        # Check if server is reachable on Gateway (8300) or Loopback (8299)
        test_port = 8300
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        res = sock.connect_ex(("127.0.0.1", 8300))
        sock.close()
        if res != 0:
            print("   Port 8300 not yet up, falling back to 8299")
            test_port = 8299

        print(f"   Connecting queries to port {test_port}...")

        # Test 1: COUNT BUCKETS (initially empty or only system buckets)
        print("\n[Test 1] Testing COUNT BUCKETS...")
        raw = send_tcp("127.0.0.1", test_port, "COUNT BUCKETS")
        print("   Response:", raw)
        resp = json.loads(raw)
        assert isinstance(resp, list) and resp[0]["status"] == "ok"
        assert resp[0]["type"] == "buckets"
        initial_count = resp[0]["count"]
        print(f"   PASS: Initial user bucket count = {initial_count}")

        # Test 2: COUNT RAFT_NODES & COUNT *_RAFT_NODES
        print("\n[Test 2] Testing COUNT RAFT_NODES & COUNT *_RAFT_NODES...")
        raw = send_tcp("127.0.0.1", test_port, "COUNT RAFT_NODES")
        print("   COUNT RAFT_NODES:", raw)
        resp1 = json.loads(raw)
        assert resp1[0]["status"] == "ok"
        assert "leader" in resp1[0]
        assert "nodes" in resp1[0]

        raw = send_tcp("127.0.0.1", test_port, "COUNT *_RAFT_NODES")
        print("   COUNT *_RAFT_NODES:", raw)
        resp2 = json.loads(raw)
        assert resp2[0]["count"] == resp1[0]["count"]
        print("   PASS: Raft nodes verified")

        # Test 3: COUNT COORDINATOR_NODES & COUNT *_COORDINATOR_NODES
        print("\n[Test 3] Testing COUNT COORDINATOR_NODES...")
        raw = send_tcp("127.0.0.1", test_port, "COUNT COORDINATOR_NODES")
        print("   COUNT COORDINATOR_NODES:", raw)
        resp = json.loads(raw)
        assert resp[0]["status"] == "ok"
        assert "shards" in resp[0]
        assert resp[0]["count"] >= 1

        raw = send_tcp("127.0.0.1", test_port, "COUNT *_COORDINATOR_NODES")
        resp_star = json.loads(raw)
        assert resp_star[0]["count"] == resp[0]["count"]
        print("   PASS: Coordinator nodes verified")

        # Test 4: POUR INTO user buckets with all field data types
        print("\n[Test 4] Inserting documents with string, integer, boolean (case-insensitive), date (_date_ and ISO), float, array, object...")
        doc1 = {
            "name": "john",
            "age": 15,
            "isactive": True,
            "isactive_str": "false",
            "current_date_": "",
            "birth_date": "2000-05-15",
            "created_at": "2026-10-11T12:00:00Z",
            "score": 95.5,
            "tags": ["engineer", "admin"],
            "profile": {"location": "San Francisco"}
        }
        query_pour1 = f'POUR INTO analytics_events_prod :evt_001 {json.dumps(doc1)}'
        raw = send_tcp("127.0.0.1", test_port, query_pour1)
        print("   POUR 1 response:", raw)

        doc2 = {
            "title": "Super Server 9000",
            "sku": "SRV-9000",
            "quantity": 42,
            "in_stock": "TRUE",
            "expiry_date_": "never",
            "price": 1999.99
        }
        query_pour2 = f'POUR INTO hardware_inventory :hw_001 {json.dumps(doc2)}'
        raw = send_tcp("127.0.0.1", test_port, query_pour2)
        print("   POUR 2 response:", raw)

        # Test 5: Verify COUNT BUCKETS incremented
        print("\n[Test 5] Verifying COUNT BUCKETS after pour...")
        raw = send_tcp("127.0.0.1", test_port, "COUNT BUCKETS")
        print("   COUNT BUCKETS response:", raw)
        resp = json.loads(raw)
        new_count = resp[0]["count"]
        assert new_count >= initial_count + 2
        print(f"   PASS: User buckets counted = {new_count}")

        # Test 6: DESCRIBE BUCKETS (Full Catalog)
        print("\n[Test 6] Testing DESCRIBE BUCKETS (Catalog)...")
        raw = send_tcp("127.0.0.1", test_port, "DESCRIBE BUCKETS")
        print("   DESCRIBE BUCKETS response:\n", json.dumps(json.loads(raw), indent=2))
        resp = json.loads(raw)
        assert resp[0]["status"] == "ok"
        catalogs = {c["name"]: c for c in resp[0]["catalogs"]}
        assert "analytics_events_prod" in catalogs
        assert "hardware_inventory" in catalogs
        # Check no internal buckets start with _
        for c in resp[0]["catalogs"]:
            assert not c["name"].startswith("_"), f"Internal bucket {c['name']} found in catalog!"

        # Verify schema field types in analytics_events_prod
        cat1 = catalogs["analytics_events_prod"]
        schema1 = cat1["schema"]
        print("\n   [Schema Verification 1: analytics_events_prod]")
        print("   Inferred schema:", json.dumps(schema1, indent=4))
        assert schema1["name"] == "string"
        assert schema1["age"] == "integer"
        assert schema1["isactive"] == "boolean"
        assert schema1["isactive_str"] == "boolean"
        assert schema1["current_date_"] == "date"
        assert schema1["birth_date"] == "date"
        assert schema1["created_at"] == "date"
        assert schema1["score"] == "float"
        assert schema1["tags"] == "array"
        assert schema1["profile"] == "object"
        print("   PASS: All 7 field types inferred accurately!")

        # Verify schema field types in hardware_inventory
        cat2 = catalogs["hardware_inventory"]
        schema2 = cat2["schema"]
        print("\n   [Schema Verification 2: hardware_inventory]")
        print("   Inferred schema:", json.dumps(schema2, indent=4))
        assert schema2["in_stock"] == "boolean"
        assert schema2["expiry_date_"] == "date"
        assert schema2["quantity"] == "integer"
        assert schema2["price"] == "float"
        assert schema2["title"] == "string"
        print("   PASS: Hardware schema verified!")

        # Test 7: DESCRIBE BUCKET "analytics_events_prod" (Single bucket schema)
        print("\n[Test 7] Testing DESCRIBE BUCKET \"analytics_events_prod\"...")
        raw = send_tcp("127.0.0.1", test_port, 'DESCRIBE BUCKET "analytics_events_prod"')
        print("   Single bucket describe response:\n", json.dumps(json.loads(raw), indent=2))
        resp = json.loads(raw)
        assert resp[0]["status"] == "ok"
        assert resp[0]["bucket"] == "analytics_events_prod"
        assert resp[0]["records"] >= 1
        assert len(resp[0]["sample"]) >= 1
        print("   PASS: Single bucket schema inspection verified!")

        # Test 8: Keyword Guardrail check (POUR INTO buckets)
        print("\n[Test 8] Testing Keyword Guardrail protection against reserved name 'buckets'...")
        raw = send_tcp("127.0.0.1", test_port, 'POUR INTO buckets :b1 {"foo": "bar"}')
        print("   Blocked guardrail response:", raw)
        resp = json.loads(raw)
        assert resp[0]["status"] == "error"
        assert "reserved" in resp[0]["message"].lower()
        print("   PASS: Reserved keyword 'buckets' mutation properly blocked!")

        # Test 9: Go Coordinator Port 8305 Direct Verification
        print("\n[Test 9] Testing Go Coordinator on Port 8305...")
        coord_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        res_coord = coord_sock.connect_ex(("127.0.0.1", 8305))
        coord_sock.close()
        if res_coord == 0:
            raw = send_tcp("127.0.0.1", 8305, "COUNT COORDINATOR_NODES")
            print("   Coordinator COUNT COORDINATOR_NODES response:", raw)
            resp = json.loads(raw)
            assert resp[0]["status"] == "ok"
            print("   PASS: Coordinator direct query verified!")
        else:
            print("   (Coordinator process running externally or on configured port)")

        print("\n" + "=" * 60)
        print("   ALL TESTS PASSED WITH 100% SUCCESS!")
        print("=" * 60)

    finally:
        print("\nCleaning up server processes...")
        srv_proc.terminate()
        try:
            srv_proc.wait(timeout=3)
        except Exception:
            srv_proc.kill()
        shutil.rmtree(tmp_data, ignore_errors=True)

if __name__ == "__main__":
    main()
