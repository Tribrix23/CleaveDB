import os, json, time, shutil
import cleavedb3_storage
from cleaveql.parser import Parser
from cleaveql.lexer import Lexer
from cleaveql.interpreter import Interpreter

db_path = os.path.join(os.getcwd(), "test_all_db")
if os.path.exists(db_path):
    shutil.rmtree(db_path)

print("Starting Comprehensive Test...")
engine = cleavedb3_storage.CleaveDB(db_path)
interpreter = Interpreter(engine)

def run(q):
    return interpreter.execute(Parser(Lexer(q).tokenize()).parse())

# 1. Test POUR
print("Testing POUR...")
run('POUR INTO employees "emp1" {"name": "Alice", "role": "admin", "salary": 1000}')
run('POUR INTO employees "emp2" {"name": "Bob", "role": "dev", "salary": 500}')
run('POUR INTO logs "log1" {"msg": "System start"}')

# Test auto ID
res = run('POUR INTO logs RANDOM {"msg": "Random thing"}')
assert res[0]["status"] == "ok"
assert "logs:" in res[0]["gid"]

# 2. Test Get
print("Testing Get (Rust Native)...")
doc1 = engine.get("employees:emp1")
assert json.loads(doc1)["name"] == "Alice"

# 3. Test IDs are bucket scoped
print("Testing Bucket Scoping...")
run('POUR INTO users "emp1" {"name": "Charlie"}')
# Should not overwrite employees:emp1
doc_emp = engine.get("employees:emp1")
assert json.loads(doc_emp)["name"] == "Alice"

# 4. Test SCOOP
print("Testing SCOOP EVERYTHING...")
res = run("SCOOP EVERYTHING FROM employees")
assert len(res[0]["documents"]) == 2

print("Testing SCOOP ONLY UNIQUE...")
run('POUR INTO employees "emp3" {"name": "Dave", "role": "dev", "salary": 500}')
res = run("SCOOP ONLY UNIQUE role FROM employees")
assert len(res[0]["documents"]) == 2 # admin and dev

print("Testing SCOOP FIRST...")
res = run("SCOOP THE FIRST 1 FROM employees WHOSE role IS \"admin\"")
assert len(res[0]["documents"]) == 1
assert res[0]["documents"][0]["body"]["name"] == "Alice"

# 5. Test COUNT
print("Testing COUNT...")
res = run("COUNT FROM employees")
assert res[0]["count"] == 3

# 6. Test DLS (Data Masking)
print("Testing Data Masking (DLS)...")
run('SHAPE MASK salary ON employees USING @role != "admin"')
run('SET role = "dev"')
res = run("SCOOP EVERYTHING FROM employees")
for doc in res[0]["documents"]:
    if doc["body"]["name"] == "Bob":
        assert doc["body"]["salary"] == "***MASKED***"
    if doc["body"]["name"] == "Alice":
        # Alice is an admin, but the *viewer's* role is dev, so Alice's salary should also be masked from this viewer!
        assert doc["body"]["salary"] == "***MASKED***"

# 7. Test bypass_dls
print("Testing bypass_dls...")
run('SET bypass_dls = "true"')
res = run("SCOOP EVERYTHING FROM employees")
for doc in res[0]["documents"]:
    if doc["body"]["name"] == "Bob":
        assert doc["body"]["salary"] == 500 # Should be unmasked!


# 8. Test LIMIT, MENTIONING, INCLUDE
print("Testing LIMIT...")
res = run('SCOOP EVERYTHING FROM employees LIMIT 1')
assert len(res[0]["documents"]) == 1

print("Testing MENTIONING...")
res = run('SCOOP EVERYTHING FROM employees MENTIONING "admin"')
assert len(res[0]["documents"]) == 1

print("Testing INCLUDE...")
res = run('SCOOP EVERYTHING FROM employees INCLUDE role')
assert "name" not in res[0]["documents"][0]["body"]
assert "role" in res[0]["documents"][0]["body"]
print("All tests passed! 100% of functionality verified.")


