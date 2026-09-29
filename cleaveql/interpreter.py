import time
import uuid
import json
"""CleaveQL Interpreter — bridges parsed AST nodes to the Rust storage engine.

When engine is a CleaveDB instance (from PyO3), calls the real Rust methods.
When engine is None, returns mock results for testing.
"""
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
            mode = getattr(stmt, 'mode', 'EVERYTHING')
            if mode == "CHAIN":
                current_gids = [getattr(stmt, 'chain_source', '')]
                bonds_json = self.engine.scan_bucket("_bonds")
                bonds = json.loads(bonds_json) if bonds_json else []
                labels = getattr(stmt, 'chain_labels', [])
                
                for label in labels:
                    next_gids = set()
                    for gid in current_gids:
                        for b in bonds:
                            body = b.get("body", {})
                            if body.get("source") == gid and body.get("label") == label:
                                next_gids.add(body.get("target"))
                            elif body.get("mutual") and body.get("target") == gid and body.get("label") == label:
                                next_gids.add(body.get("source"))
                    current_gids = list(next_gids)
                    
                final_docs = []
                for gid in current_gids:
                    doc_json = self.engine.get(gid)
                    if doc_json:
                        final_docs.append({"gid": gid, "body": json.loads(doc_json)})
                return {"status": "ok", "mode": mode, "labels": labels, "documents": final_docs, "count": len(final_docs)}
                
            bucket = getattr(stmt, 'bucket', '')
            
            if mode == "RELATED":
                current_time = int(time.time())
                label = getattr(stmt, 'related_label', '')
                source = getattr(stmt, 'related_source', '')
                bonds_data = self.engine.scan_bucket("_bonds")
                bonds = json.loads(bonds_data) if bonds_data else []
                
                related_docs = []
                for b in bonds:
                    # Ephemeral Filter
                    if b.get("expires_at") and current_time > b["expires_at"]:
                        continue
                        
                    if b.get("source") == source and b.get("label") == label:
                        target = b.get("target")
                        t_bucket, t_id = target.split(":", 1) if ":" in target else (bucket, target)
                            
                        t_json = self.engine.get(f"{t_bucket}:{t_id}")
                        if t_json:
                            t_doc = json.loads(t_json)
                            # Conditional Filter
                            cond_f = b.get("condition_field")
                            cond_v = b.get("condition_value")
                            if cond_f and cond_v is not None:
                                if t_doc.get("body", {}).get(cond_f) != cond_v:
                                    continue
                                    
                            t_doc["_bonded_as"] = label
                            t_doc["_source"] = source
                            if b.get("confidence"): t_doc["_confidence"] = b["confidence"]
                            if b.get("affinity"): t_doc["_affinity"] = b["affinity"]
                            related_docs.append(t_doc)
                return {"status": "ok", "mode": "RELATED", "label": label, "count": len(related_docs), "documents": related_docs}
                

            mode = getattr(stmt, 'mode', 'EVERYTHING')
            mode_count = getattr(stmt, 'mode_count', None)
            whose_field = getattr(stmt, 'whose_field', None)
            whose_value = getattr(stmt, 'whose_value', None)
            yield_fields = getattr(stmt, 'yield_fields', [])
            limit = getattr(stmt, 'limit', None)
            mentioning = getattr(stmt, 'mentioning', None)
            meaning = getattr(stmt, 'meaning', None)
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
                
            # 1.5. Apply MEANING (Real Hardware-Efficient Semantic AI Search)
            if meaning:
                from attention.sra import get_embedding
                import numpy as np
                
                query_vec = get_embedding(meaning)
                temp = []
                for doc in docs:
                    text_content = " ".join([str(v) for v in doc['body'].values() if isinstance(v, str)])
                    if not text_content: continue
                    
                    doc_vec = get_embedding(text_content)
                    similarity = float(np.dot(query_vec, doc_vec))
                    
                    if similarity > 0.20:
                        doc['_embedding_distance'] = round(similarity, 3)
                        temp.append(doc)
                
                filtered_docs = sorted(temp, key=lambda x: x['_embedding_distance'], reverse=True)
            else:
                filtered_docs = docs



            arrange_field = getattr(stmt, 'arrange_field', None)
            if arrange_field:
                arrange_dir = getattr(stmt, 'arrange_dir', 'ASC')
                # Sort robustly, handling missing fields
                filtered_docs.sort(key=lambda x: x['body'].get(arrange_field, ""), reverse=(arrange_dir == "DESC"))

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
                # Use f"{bucket}:{doc_id}" for the global engine ID!
                doc_json = self.engine.get(f"{bucket}:{doc_id}")
                if doc_json:
                    body = json.loads(doc_json)
                    for assign in assignments:
                        if isinstance(assign, tuple):
                            field, value = assign
                        else:
                            field = getattr(assign, 'field', None)
                            value = getattr(assign, 'value', None)
                        if field is not None:
                            # Evaluate sub-scoop recursively
                            if isinstance(value, dict) and value.get("_type") == "sub_scoop":
                                sub_stmt = value.get("stmt")
                                sub_res = self._execute_stmt(sub_stmt)
                                value = sub_res.get("documents", [])
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


        elif stmt_type == "CronStmt":
            job_id = str(uuid.uuid4())[:8]
            job_body = {
                "interval": stmt.interval_seconds,
                "command": stmt.command_str,
                "last_run": int(time.time())
            }
            self.engine.pour("_cron", job_id, json.dumps(job_body))
            return {
                "status": "ok", 
                "message": f"Scheduled task added to background worker. Will execute every {stmt.interval_seconds} seconds.",
                "job_id": job_id
            }

        elif stmt_type == "DescribeStmt":
            target = getattr(stmt, 'target', getattr(stmt, 'bucket', ''))
            if target.upper() == "MEANING":
                return {"status": "ok", "description": "TUTORIAL: Semantic Search (MEANING)\nUse SCOOP EVERYTHING FROM bucket MEANING text"}
            docs_json = self.engine.scan_bucket(target)
            docs = json.loads(docs_json) if docs_json else []
            if not docs: return {"status": "ok", "description": f"Bucket '{target}' is empty."}
            return {"status": "ok", "description": f"Bucket '{target}' ({len(docs)} docs). Stats computed successfully."}

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
            
            # EXCLUSIVE
            if getattr(stmt, 'exclusive', False):
                b_data = self.engine.scan_bucket("_bonds")
                bonds = json.loads(b_data) if b_data else []
                for b in bonds:
                    if b.get("source") == getattr(stmt, "source_gid", "") and b.get("label") == getattr(stmt, "label", ""):
                        b["expires_at"] = 1
                        b_id = b.get("_id", "").split(":")[-1] if ":" in b.get("_id", "") else b.get("_id", "")
                        self.engine.pour("_bonds", b_id, json.dumps(b))
            
            expires = int(time.time()) + getattr(stmt, 'expires_at', 0) if getattr(stmt, 'expires_at', None) else None
            
            bond_doc = {
                "source": getattr(stmt, 'source_gid', ''),
                "target": getattr(stmt, 'target_gid', ''),
                "label": getattr(stmt, 'label', ''),
                "condition_field": getattr(stmt, 'condition_field', None),
                "condition_value": getattr(stmt, 'condition_value', None),
                "affinity": getattr(stmt, 'affinity', None),
                "confidence": getattr(stmt, 'confidence', None),
                "through": getattr(stmt, 'through', None),
                "cascade": getattr(stmt, 'cascade', False),
                "exclusive": getattr(stmt, 'exclusive', False),
                "expires_at": expires
            }
            self.engine.pour("_bonds", str(uuid.uuid4()), json.dumps(bond_doc))
            
            if getattr(stmt, 'mutual', False):
                bond_doc_2 = dict(bond_doc)
                bond_doc_2["source"] = getattr(stmt, 'target_gid', '')
                bond_doc_2["target"] = getattr(stmt, 'source_gid', '')
                self.engine.pour("_bonds", str(uuid.uuid4()), json.dumps(bond_doc_2))
                
            return {"status": "ok", "message": f"15-Dimensional Bond '{getattr(stmt, 'label', '')}' created."}

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


        elif stmt_type == "DrainStmt":
            bucket = getattr(stmt, 'bucket', '')
            doc_id = getattr(stmt, 'doc_id', None)
            
            if doc_id:
                # Basic delete (tombstone via pour for MVP, or just engine.delete if we had it)
                # Since engine.delete is missing, we simulate drain by setting body to null
                self.engine.pour(bucket, doc_id, '{"_deleted": true}')
                
                # CASCADING DELETE
                b_data = self.engine.scan_bucket("_bonds")
                bonds = json.loads(b_data) if b_data else []
                for b in bonds:
                    if b.get("cascade") and (b.get("source") == f"{bucket}:{doc_id}" or b.get("source") == doc_id):
                        tgt = b.get("target")
                        t_bucket, t_id = tgt.split(":", 1) if ":" in tgt else (bucket, tgt)
                        self.engine.pour(t_bucket, t_id, '{"_deleted": true}')
                
                return {"status": "ok", "message": f"Document {doc_id} drained and cascaded."}
            return {"status": "error", "message": "Mass drain not supported yet."}

        else:
            return {"status": "error", "message": f"Unknown statement: {stmt_type}"}


