import os
import sys
sys.path.insert(0, os.path.abspath("."))
import shutil
import json
import cleavedb3_storage
from cleaveql.lexer import Lexer
from cleaveql.parser import Parser
from cleaveql.interpreter import Interpreter
from queue import Queue

TEST_DIR = "test_research_db"
if os.path.exists(TEST_DIR):
    shutil.rmtree(TEST_DIR)

print("=" * 70)
print("TESTING CLEAVEDB ASYNCHRONOUS REFERENTIAL FABRIC & LATE-BINDING BONDS")
print("=" * 70)

db = cleavedb3_storage.CleaveDB(TEST_DIR)
queue = Queue()
interpreter = Interpreter(db, queue)
interpreter.set_context({"user": "admin", "auth_level": "dev"})

def run_query(q):
    print(f"\n[QUERY] > {q}")
    tokens = Lexer(q).tokenize()
    stmts = Parser(tokens).parse()
    res = interpreter.execute(stmts)
    print(f"[RESULT] {json.dumps(res, indent=2)}")
    return res

# 1. Pour source document
run_query('POUR INTO orders "ord_101" {"total": 450.0, "item": "Laptop"}')

# 2. Check Phantom stats initially
print("\n[PHANTOM LATTICE STATS (Initial)]")
print(db.phantom_stats())

# 3. Create a LATE-BINDING BOND to a non-existent target "customers:c42"
res_bond = run_query('BOND "orders:ord_101" TO "customers:c42" AS "purchased_by"')
assert "latched" in res_bond[0].get("message", "").lower() or res_bond[0].get("status") == "ok", "Bond failed to latch!"

# 4. Show pending bonds in the Phantom Lattice
res_pending = run_query('SHOW PENDING')
assert res_pending[0].get("count") >= 1, "Expected pending bond in Phantom Lattice!"

# 5. Graph traversal before target exists (with ALLOWING UNRESOLVED / candidate mode)
res_find_pending = run_query('FIND CANDIDATE "purchased_by" OF "orders:ord_101"')
assert len(res_find_pending[0].get("documents", [])) == 1, "Expected virtual bond token!"
print("[VERIFIED] Virtual pending node correctly yielded for unmaterialized target!")

# 6. Now pour the TARGET document "customers:c42" (The Cleave-Snap event)
print("\n--- POURING TARGET: TRIGGERING CLEAVE-SNAP PROTOCOL ---")
run_query('POUR INTO customers "c42" {"name": "Alice Smith", "tier": "Gold"}')

# 7. Check graph traversal after target arrives
res_find_fused = run_query('FIND "purchased_by" OF "orders:ord_101"')
docs = res_find_fused[0].get("documents", [])
assert len(docs) == 1, "Expected fused document!"
assert docs[0]["body"]["name"] == "Alice Smith", "Expected Alice Smith in joined body!"
print("\n[VERIFIED] Cleave-Snap automatically fused the relationship upon target arrival!")

# 8. Test HEAL — ensure it doesn't corrupt or destroy valid bonds
print("\n--- TESTING HEAL RECONCILIATION ---")
run_query('HEAL BONDS')
res_check_again = run_query('FIND "purchased_by" OF "orders:ord_101"')
assert len(res_check_again[0].get("documents", [])) == 1, "Bond lost after HEAL!"

print("\n" + "=" * 70)
print("ALL ASYNCHRONOUS REFERENTIAL FABRIC TESTS PASSED PERFECTLY!")
print("=" * 70)

# Cleanup
shutil.rmtree(TEST_DIR, ignore_errors=True)
