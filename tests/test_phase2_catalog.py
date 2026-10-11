import unittest
import tempfile
import json
import cleavedb3_storage
from cleaveql.lexer import Lexer
from cleaveql.parser import Parser, ParseError
from cleaveql.interpreter import Interpreter, infer_field_type, infer_schema_from_docs, format_size_bytes


class TestPhase2Catalog(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db = cleavedb3_storage.CleaveDB(self.tmp_dir.name)
        self.interp = Interpreter(self.db)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def run_query(self, q: str):
        tokens = Lexer(q).tokenize()
        stmts = Parser(tokens).parse()
        return self.interp.execute(stmts)

    def test_schema_field_inference_types(self):
        # 1. string
        self.assertEqual(infer_field_type("name", "john"), "string")
        # 2. integer
        self.assertEqual(infer_field_type("age", 15), "integer")
        self.assertEqual(infer_field_type("count", 0), "integer")
        # 3. boolean (real bool & case-insensitive string bool)
        self.assertEqual(infer_field_type("isactive", True), "boolean")
        self.assertEqual(infer_field_type("isactive", False), "boolean")
        self.assertEqual(infer_field_type("isactive", "true"), "boolean")
        self.assertEqual(infer_field_type("isactive", "True"), "boolean")
        self.assertEqual(infer_field_type("isactive", "FALSE"), "boolean")
        # 4. date with _date_ in name
        self.assertEqual(infer_field_type("current_date_", ""), "date")
        self.assertEqual(infer_field_type("user_date_created", "val"), "date")
        self.assertEqual(infer_field_type("date_of_birth", "2000-01-01"), "date")
        self.assertEqual(infer_field_type("birth_date", "2000-01-01"), "date")
        self.assertEqual(infer_field_type("created_at", "2026-10-11T12:00:00Z"), "date")
        # 5. date from ISO 8601 value
        self.assertEqual(infer_field_type("event_time", "2026-10-11"), "date")
        self.assertEqual(infer_field_type("event_time", "2026-10-11T15:30:00Z"), "date")
        # 6. float
        self.assertEqual(infer_field_type("price", 19.99), "float")
        # 7. array & object
        self.assertEqual(infer_field_type("tags", ["a", "b"]), "array")
        self.assertEqual(infer_field_type("meta", {"env": "prod"}), "object")

    def test_count_buckets_empty_and_ignoring_internal(self):
        # 1. When no buckets exist
        res = self.run_query("COUNT BUCKETS")
        self.assertEqual(res, [{"status": "ok", "count": 0, "type": "buckets"}])

        # 2. Pour into user buckets and an internal bucket (using dev context for internal)
        self.run_query('POUR INTO users :u1 {"name":"alice", "age":25}')
        self.run_query('POUR INTO products :p1 {"title":"Keyboard", "price":49.99}')
        # Internal bucket should not count
        self.db.pour("_internal_cache", "c1", json.dumps({"cached": True}))

        res = self.run_query("COUNT BUCKETS")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["status"], "ok")
        self.assertEqual(res[0]["count"], 2)
        self.assertEqual(res[0]["type"], "buckets")

        # Singular alias: COUNT BUCKET
        res_alias = self.run_query("COUNT BUCKET")
        self.assertEqual(res_alias, [{"status": "ok", "count": 2, "type": "buckets"}])

    def test_count_raft_nodes(self):
        # COUNT RAFT_NODES
        res1 = self.run_query("COUNT RAFT_NODES")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["status"], "ok")
        self.assertIn("count", res1[0])
        self.assertIn("leader", res1[0])
        self.assertIn("replicas", res1[0])
        self.assertIn("nodes", res1[0])

        # COUNT *_RAFT_NODES
        res2 = self.run_query("COUNT *_RAFT_NODES")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["status"], "ok")
        self.assertEqual(res2[0]["count"], res1[0]["count"])

    def test_count_coordinator_nodes(self):
        # COUNT COORDINATOR_NODES
        res1 = self.run_query("COUNT COORDINATOR_NODES")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["status"], "ok")
        self.assertIn("count", res1[0])
        self.assertIn("shards", res1[0])
        self.assertIsInstance(res1[0]["shards"], list)

        # COUNT *_COORDINATOR_NODES
        res2 = self.run_query("COUNT *_COORDINATOR_NODES")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["status"], "ok")
        self.assertEqual(res2[0]["count"], res1[0]["count"])

    def test_describe_buckets_catalog(self):
        # Empty catalog
        res_empty = self.run_query("DESCRIBE BUCKETS")
        self.assertEqual(res_empty, [{"status": "ok", "count": 0, "catalogs": []}])

        # Populate buckets
        self.run_query('''POUR INTO analytics_events_prod :e1 {
            "user_id": "u101",
            "event_type": "click",
            "count": 12,
            "is_active": true,
            "event_date_": "2026-10-11"
        }''')
        self.run_query('''POUR INTO users :u1 {
            "name": "john",
            "age": 15,
            "isactive": "true",
            "current_date_": ""
        }''')
        # Add an internal bucket that should be omitted
        self.db.pour("_auth", "admin", json.dumps({"role": "root"}))

        res = self.run_query("DESCRIBE BUCKETS")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["status"], "ok")
        self.assertEqual(res[0]["count"], 2)
        
        catalogs = {c["name"]: c for c in res[0]["catalogs"]}
        self.assertIn("analytics_events_prod", catalogs)
        self.assertIn("users", catalogs)
        self.assertNotIn("_auth", catalogs)

        # Validate analytics_events_prod catalog fields
        evt = catalogs["analytics_events_prod"]
        self.assertEqual(evt["status"], "Online")
        self.assertEqual(evt["storage_engine"], "Columnar LSM")
        self.assertEqual(evt["records"], 1)
        self.assertGreater(evt["size_bytes"], 0)
        self.assertIn("B", evt["size"])
        self.assertIn("last_active", evt)
        self.assertEqual(evt["schema"], {
            "user_id": "string",
            "event_type": "string",
            "count": "integer",
            "is_active": "boolean",
            "event_date_": "date"
        })

        # Validate users catalog fields
        u = catalogs["users"]
        self.assertEqual(u["status"], "Online")
        self.assertEqual(u["storage_engine"], "Document Vector")
        self.assertEqual(u["records"], 1)
        self.assertEqual(u["schema"], {
            "name": "string",
            "age": "integer",
            "isactive": "boolean",
            "current_date_": "date"
        })

    def test_describe_single_bucket_schema(self):
        self.run_query('''POUR INTO users :u1 {"name":"john", "age":15, "isactive":true, "current_date_":""}''')
        self.run_query('''POUR INTO users :u2 {"name":"alice", "age":22, "isactive":false, "rating":4.9}''')

        # Syntax 1: DESCRIBE BUCKET "users"
        res1 = self.run_query('DESCRIBE BUCKET "users"')
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["status"], "ok")
        self.assertEqual(res1[0]["bucket"], "users")
        self.assertEqual(res1[0]["records"], 2)
        self.assertEqual(res1[0]["schema"]["name"], "string")
        self.assertEqual(res1[0]["schema"]["age"], "integer")
        self.assertEqual(res1[0]["schema"]["isactive"], "boolean")
        self.assertEqual(res1[0]["schema"]["current_date_"], "date")
        self.assertEqual(res1[0]["schema"]["rating"], "float")
        self.assertEqual(len(res1[0]["sample"]), 2)

        # Syntax 2: DESCRIBE "users"
        res2 = self.run_query('DESCRIBE "users"')
        self.assertEqual(res2[0]["bucket"], "users")

        # Syntax 3: DESCRIBE users
        res3 = self.run_query('DESCRIBE users')
        self.assertEqual(res3[0]["bucket"], "users")

    def test_describe_nonexistent_bucket(self):
        res = self.run_query('DESCRIBE "nonexistent_bucket"')
        self.assertEqual(res[0]["status"], "error")
        self.assertIn("does not exist", res[0]["message"])

    def test_reserved_bucket_name_protection_cross_check(self):
        with self.assertRaises(ParseError) as ctx:
            self.run_query('POUR INTO buckets :b1 {"data": 123}')
        self.assertIn("Cannot use reserved keyword 'buckets'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
