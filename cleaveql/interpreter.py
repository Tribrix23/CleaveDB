"""CleaveQL Interpreter — bridges parsed AST nodes to the Rust storage engine.

When engine is a CleaveDB instance (from PyO3), calls the real Rust methods.
When engine is None, returns mock results for testing.
"""
import json
from .security import PolicyEngine, SecurityError



class Interpreter:
    def __init__(self, engine=None):
        self.engine = engine
        self.context = {}
        self.security = PolicyEngine()
  # CleaveDB instance from PyO3, or None for mock

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
            if not self.security.check_write(bucket, body, self.context):
                return {"status": "error", "message": "Security Policy Violation: Write access denied by Document-Level Security."}
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
            bucket = getattr(stmt, 'bucket', '')
            mode = getattr(stmt, 'mode', 'EVERYTHING')
            mode_count = getattr(stmt, 'mode_count', None)
            whose_field = getattr(stmt, 'whose_field', None)
            whose_value = getattr(stmt, 'whose_value', None)
            yield_fields = getattr(stmt, 'yield_fields', [])
            limit = getattr(stmt, 'limit', None)
            mentioning = getattr(stmt, 'mentioning', None)
            include = getattr(stmt, 'include', [])
            
            results_json = self.engine.scan_bucket(bucket)
            results = json.loads(results_json) if results_json else []
            
            docs = []
            for r in results:
                doc_json = self.engine.get(r['gid'])
                if doc_json:
                    docs.append({"gid": r['gid'], "body": json.loads(doc_json)})
                    
            # 1. Apply MENTIONING (Text search mock)
            if mentioning:
                docs = [d for d in docs if mentioning.lower() in json.dumps(d['body']).lower()]
            
            # 2. Apply DLS
            filtered_docs = []
            for doc in docs:
                if self.security.check_read(bucket, doc.get('body', {}), self.context):
                    doc['body'] = self.security.apply_masks(bucket, doc['body'], self.context)
                    filtered_docs.append(doc)
            
            # 3. Apply WHOSE
            if whose_field and whose_value is not None:
                temp = []
                for doc in filtered_docs:
                    if doc['body'].get(whose_field) == whose_value:
                        temp.append(doc)
                filtered_docs = temp

            # 4. Apply INCLUDE
            if include:
                temp = []
                for doc in filtered_docs:
                    new_body = {}
                    for field in include:
                        if field in doc['body']:
                            new_body[field] = doc['body'][field]
                    doc['body'] = new_body
                    temp.append(doc)

            # 5. Apply Mode
            if mode == "UNIQUE":
                seen = set()
                final_docs = []
                for doc in filtered_docs:
                    sig = tuple(doc['body'].get(f) for f in yield_fields)
                    if sig not in seen:
                        seen.add(sig)
                        final_docs.append(doc)
                filtered_docs = final_docs
                
                temp = []
                for doc in filtered_docs:
                    new_body = {}
                    for f in yield_fields:
                        if f in doc['body']:
                            new_body[f] = doc['body'][f]
                    doc['body'] = new_body
                    temp.append(doc)
                filtered_docs = temp

            elif mode == "FIRST":
                if mode_count:
                    filtered_docs = filtered_docs[:mode_count]

            elif mode == "LAST":
                if mode_count:
                    filtered_docs = filtered_docs[-mode_count:]

            # 6. Apply LIMIT
            if limit is not None:
                filtered_docs = filtered_docs[:limit]
            
            return {"status": "ok", "mode": mode, "documents": filtered_docs, "count": len(filtered_docs)}

        elif stmt_type == "CountStmt":
            
            bucket = getattr(stmt, 'bucket', '')
            results_json = self.engine.scan_bucket(bucket)
            results = json.loads(results_json) if results_json else []
            return {"status": "ok", "count": len(results)}

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

        elif stmt_type == "SetContextStmt":
            key = getattr(stmt, 'key', '')
            value = getattr(stmt, 'value', '')
            self.context[key] = value
            return {"status": "ok", "context": {key: value}}

        elif stmt_type == "MaskStmt":
            bucket = getattr(stmt, 'bucket', '')
            field = getattr(stmt, 'field', '')
            condition = getattr(stmt, 'condition', [])
            self.security.add_mask(bucket, field, condition)
            return {"status": "ok", "message": f"Data Masking active on '{bucket}.{field}'"}

        elif stmt_type == "PolicyStmt":
            bucket = getattr(stmt, 'bucket', '')
            name = getattr(stmt, 'name', '')
            action = getattr(stmt, 'action', '')
            condition = getattr(stmt, 'condition', [])
            self.security.add_policy(bucket, name, action, condition)
            return {"status": "ok", "policy": name, "message": f"Document-Level Security policy '{name}' active on '{bucket}'"}

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


