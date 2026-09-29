import os, json, shutil
from cleaveql.lexer import Lexer
from cleaveql.parser import Parser
from cleaveql.interpreter import Interpreter
import cleavedb3_storage

db_path = os.path.join(os.getcwd(), "final_test_db")
if os.path.exists(db_path):
    shutil.rmtree(db_path)

engine = cleavedb3_storage.CleaveDB(db_path)
interp = Interpreter(engine)

def run_query(title, query):
    print(f"\n[{title}]")
    print(f"cleavedb> {query}")
    try:
        stmts = Parser(Lexer(query).tokenize()).parse()
        results = interp.execute(stmts)
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(f"Error: {e}")

print("=======================================")
print(" CleaveDB 3.0: Final End-to-End Test")
print("=======================================")

# 1. Test POUR RANDOM (Auto ID)
run_query("1. Insert Auto-Generated IDs (POUR RANDOM)", 
'''POUR MANY INTO users [
  {"_test": "test", "name": "Alice", "role": "admin", "department": "engineering", "salary": 120000},
  {"_test": "test", "name": "Bob", "role": "dev", "department": "engineering", "salary": 95000},
  {"_test": "test", "name": "Charlie", "role": "dev", "department": "marketing", "salary": 85000},
  {"_test": "test", "name": "Diana", "role": "manager", "department": "engineering", "salary": 140000}
]''')

# 2. Test Security (Data Masking)
run_query("2. Define Data Masking Policy", 'SHAPE MASK salary ON users USING @role != "admin"')

# 3. Test Conversational QL (SCOOP EVERYTHING) + Masking
run_query("3. Set Context to Developer", 'SET role = "dev"')
run_query("4. Extract Everything (Notice salary is MASKED)", 'SCOOP EVERYTHING FROM users')

# 4. Test UNIQUE
run_query("5. Extract Only Unique Departments", 'SCOOP ONLY UNIQUE department FROM users')

# 5. Test FIRST + Predicates
run_query("6. Extract the First 2 Engineers", 'SCOOP THE FIRST 2 FROM users WHOSE department IS "engineering"')

print("\n=======================================")
