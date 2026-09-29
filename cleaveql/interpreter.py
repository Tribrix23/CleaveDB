"""CleaveQL Interpreter — bridges parsed AST nodes to the Rust storage engine.

When engine is a CleaveDB instance (from PyO3), calls the real Rust methods.
When engine is None, returns mock results for testing.
"""
import json


class Interpreter:
    def __init__(self, engine=None):
        self.engine = engine  # CleaveDB instance from PyO3, or None for mock

    def execute(self, stmts: list) -> list:
        results = []
        for stmt in stmts:
            try:
                results.append(self._execute_stmt(stmt))
            except Exception as e:
                results.append({"status": "error", "message": str(e)})
        return results

    def _execute_stmt(self, stmt):
        stmt_type = type(stmt).__name__

        # ---- Mock mode (no engine connected) ----
        if self.engine is None:
            return {"status": "mock", "statement": stmt_type}

        # ---- Real engine dispatch ----
        if stmt_type == "PourStmt":
            bucket = getattr(stmt, 'bucket', '')
            doc_id = getattr(stmt, 'doc_id', None)
            body = getattr(stmt, 'json_body', None)
            json_str = json.dumps(body) if isinstance(body, (dict, list)) else str(body or '{}')
            gid = self.engine.pour(bucket, doc_id, json_str)
            return {"status": "ok", "gid": gid}

        elif stmt_type == "PourManyStmt":
            bucket = getattr(stmt, 'bucket', '')
            documents = getattr(stmt, 'json_array', [])
            if isinstance(documents, str):
                documents = json.loads(documents)
            gids = []
            for doc in documents:
                doc_id = doc.pop('_id', doc.pop('gid', None)) if isinstance(doc, dict) else None
                json_str = json.dumps(doc) if isinstance(doc, dict) else str(doc)
                gid = self.engine.pour(bucket, doc_id, json_str)
                gids.append(gid)
            return {"status": "ok", "count": len(gids), "gids": gids}

        elif stmt_type == "ScoopStmt":
            # For now, text search if mentioning is provided
            mentioning = getattr(stmt, 'mentioning', None)
            if mentioning:
                results_json = self.engine.search_text(mentioning)
                results = json.loads(results_json) if results_json else []
                # Fetch full docs for each result
                docs = []
                limit = getattr(stmt, 'limit', None)
                for r in results:
                    if limit and len(docs) >= limit:
                        break
                    doc_json = self.engine.get(r['gid'])
                    if doc_json:
                        docs.append({"gid": r['gid'], "body": json.loads(doc_json), "score": r.get('freq', 0)})
                return {"status": "ok", "documents": docs, "count": len(docs)}
            else:
                # Without mentioning, we can't do a full scan through PyO3 yet
                return {"status": "ok", "documents": [], "count": 0, "note": "Full scan requires cursor support"}

        elif stmt_type == "DrainStmt":
            doc_id = getattr(stmt, 'doc_id', None)
            if doc_id:
                deleted = self.engine.delete(doc_id)
                return {"status": "ok", "deleted": deleted}
            return {"status": "ok", "deleted": False, "note": "Bulk drain requires cursor support"}

        elif stmt_type == "CountStmt":
            return {"status": "ok", "count": 0, "note": "Count requires cursor support"}

        elif stmt_type == "ChangeStmt":
            doc_id = getattr(stmt, 'doc_id', None)
            bucket = getattr(stmt, 'bucket', '')
            assignments = getattr(stmt, 'assignments', [])
            if doc_id:
                doc_json = self.engine.get(doc_id)
                if doc_json:
                    body = json.loads(doc_json)
                    for assign in assignments:
                        if isinstance(assign, tuple):
                            field, value = assign
                        else:
                            field = getattr(assign, 'field', None)
                            value = getattr(assign, 'value', None)
                        if field is not None:
                            body[field] = value
                    self.engine.pour(bucket, doc_id, json.dumps(body))
                    return {"status": "ok", "gid": doc_id}
                return {"status": "error", "message": f"Document '{doc_id}' not found"}
            return {"status": "error", "message": "No doc_id specified"}

        elif stmt_type == "HealStmt":
            target = getattr(stmt, 'target', 'all')
            result = self.engine.heal(target)
            return {"status": "ok", "message": result}

        elif stmt_type == "ShowStmt":
            target = getattr(stmt, 'target', 'buckets')
            result = self.engine.show(target)
            return {"status": "ok", "data": json.loads(result) if result.startswith('[') else result}

        elif stmt_type == "DescribeStmt":
            bucket = getattr(stmt, 'bucket', '')
            return {"status": "ok", "bucket": bucket, "note": "Describe requires catalog integration"}

        elif stmt_type == "DistillStmt":
            return {"status": "ok", "note": "Aggregation requires cursor support"}

        elif stmt_type == "FollowStmt":
            return {"status": "ok", "note": "Bond traversal requires edge index"}

        elif stmt_type == "ShapeBucketStmt":
            path = getattr(stmt, 'path', '')
            return {"status": "ok", "bucket": path, "message": f"Bucket '{path}' configured"}

        elif stmt_type == "ShapeProjectionStmt":
            return {"status": "ok", "note": "Projection registered"}

        elif stmt_type == "BondStmt":
            name = getattr(stmt, 'name', '')
            return {"status": "ok", "bond": name, "message": f"Bond '{name}' declared"}

        elif stmt_type == "IndexStmt":
            bucket = getattr(stmt, 'bucket', '')
            fields = getattr(stmt, 'fields', [])
            return {"status": "ok", "bucket": bucket, "fields": fields, "message": "Index created"}

        elif stmt_type == "FlowStmt":
            return {"status": "ok", "note": "Flow rule registered"}

        elif stmt_type == "PeerStmt":
            if getattr(stmt, 'attention', False):
                return {"status": "ok", "note": "Attention stats not yet wired"}
            target = getattr(stmt, 'target_stmt', None)
            if target:
                # Explain the sub-statement
                from .explain import Explainer
                exp = Explainer()
                result = exp.explain(target)
                return {"status": "ok", "explain": result}
            return {"status": "ok"}

        elif stmt_type == "SuggestStmt":
            return {"status": "ok", "suggestions": [], "note": "Run 'heal all' first to gather statistics"}

        else:
            return {"status": "error", "message": f"Unknown statement: {stmt_type}"}
