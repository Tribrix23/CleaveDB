import json
import csv
import time
from .ast import PourStmt, ScoopStmt
from .interpreter import Interpreter

class DataLoader:
    def __init__(self, engine=None):
        self.interpreter = Interpreter(engine)

    @staticmethod
    def load_jsonl(filepath, bucket, engine=None):
        interpreter = Interpreter(engine)
        count = 0
        errors = 0
        start = time.time()
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                    doc_id = doc.pop('_id', doc.pop('gid', None))
                    stmt = PourStmt(bucket=bucket, doc_id=doc_id, json_body=doc)
                    interpreter.execute([stmt])
                    count += 1
                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"  Warning: line {line_num}: {e}")
        elapsed = time.time() - start
        rate = count / elapsed if elapsed > 0 else 0
        print(f"Loaded {count} documents into '{bucket}' ({errors} errors) in {elapsed:.2f}s ({rate:.0f} docs/sec)")
        return count

    @staticmethod
    def load_csv(filepath, bucket, engine=None):
        interpreter = Interpreter(engine)
        count = 0
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                doc = {}
                for k, v in row.items():
                    try:
                        doc[k] = int(v)
                    except ValueError:
                        try:
                            doc[k] = float(v)
                        except ValueError:
                            doc[k] = v
                stmt = PourStmt(bucket=bucket, json_body=doc)
                interpreter.execute([stmt])
                count += 1
        print(f"Loaded {count} rows from CSV into '{bucket}'")
        return count

    @staticmethod
    def dump_jsonl(filepath, bucket, engine=None):
        interpreter = Interpreter(engine)
        stmt = ScoopStmt(bucket=bucket, limit=None)
        results = interpreter.execute([stmt])
        count = 0
        with open(filepath, 'w', encoding='utf-8') as f:
            for result in results:
                if isinstance(result, list):
                    for doc in result:
                        f.write(json.dumps(doc, default=str) + "\n")
                        count += 1
                elif isinstance(result, dict) and 'documents' in result:
                    for doc in result['documents']:
                        f.write(json.dumps(doc, default=str) + "\n")
                        count += 1
        print(f"Exported {count} documents from '{bucket}' to {filepath}")
        return count
