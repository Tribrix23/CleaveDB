import json

class DataLoader:
    @staticmethod
    def load_jsonl(filepath, bucket, db_engine):
        with open(filepath, 'r') as f:
            for line in f:
                doc = json.loads(line)
                db_engine.pour(bucket, doc)
        print(f"Loaded {filepath} into {bucket}")

    @staticmethod
    def dump_jsonl(filepath, bucket, db_engine):
        docs = db_engine.scoop(bucket, limit=None)
        with open(filepath, 'w') as f:
            for doc in docs:
                f.write(json.dumps(doc) + "\n")
        print(f"Dumped {bucket} into {filepath}")
