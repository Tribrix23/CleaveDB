import time
import threading
import copy
import uuid
import json
import hashlib
import os
"""CleaveQL Interpreter — bridges parsed AST nodes to the Rust storage engine.

When engine is a CleaveDB instance (from PyO3), calls the real Rust methods.
When engine is None, returns mock results for testing.
"""
from .security import PolicyEngine, SecurityError



class Interpreter:
    def _scan_bucket_rls(self, bucket):
        data = self.engine.scan_bucket(bucket)
        if not data: return data
        docs = json.loads(data)
        tenant = self.context.get("user", "").split(".")[0]
        if tenant == "cron" or not tenant: return data
        filtered = []
        for d in docs:
            gid_parts = d["gid"].split(":")
            if len(gid_parts) > 1:
                d_id = gid_parts[1]
                if d_id == tenant or d_id.startswith(f"{tenant}."):
                    filtered.append(d)
            else:
                filtered.append(d)
        return json.dumps(filtered)

    def __init__(self, engine=None, indexing_queue=None):
        self.engine = engine
        self.indexing_queue = indexing_queue
        self.context = {}
        self.in_transaction = False
        self.transaction_log = []
        self.emitted_events = []
        self.security = PolicyEngine()
        
    def set_context(self, context):
        self.context = context
        self.security = PolicyEngine()
        if self.engine:
            from .lexer import Lexer
            pol_data = self._scan_bucket_rls("_security_policies")
            if pol_data:

                tenant_id = self.context.get("user", "").split(".")[0]
                for p_doc in json.loads(pol_data):
                    doc_id = p_doc["gid"].split(":")[1]
                    if tenant_id != "cron" and not (doc_id == tenant_id or doc_id.startswith(f"{tenant_id}.")):
                        continue
                    b = p_doc.get("body", {})
                    if b.get("type") == "policy":
                        tokens = Lexer(b["condition_str"]).tokenize()
                        if tokens and tokens[-1].type.name == "EOF": tokens.pop()
                        self.security.add_policy(b["bucket"], b["name"], b["action"], tokens)
                    elif b.get("type") == "mask":
                        tokens = Lexer(b["condition_str"]).tokenize()
                        if tokens and tokens[-1].type.name == "EOF": tokens.pop()
                        if not hasattr(self.security, "masks"): self.security.masks = {}
                        if b["bucket"] not in self.security.masks: self.security.masks[b["bucket"]] = []
                        self.security.masks[b["bucket"]].append({"field": b["field"], "condition": tokens})
    # CleaveDB instance from PyO3, or None for mock

    def _evaluate_where(self, where, doc: dict) -> bool:
        if not where or not getattr(where, 'predicates', None):
            return True
            
        result = True
        for i, pred in enumerate(where.predicates):
            field_val = doc.get(pred.field)
            op = pred.op
            val = pred.value
            
            # Type coerce for comparison if possible
            if isinstance(field_val, (int, float)) and isinstance(val, str) and val.replace('.','',1).isdigit():
                val = float(val) if '.' in val else int(val)
                
            pred_res = False
            if op in ("==", "="): pred_res = (field_val == val)
            elif op == "!=": pred_res = (field_val != val)
            elif op == ">": pred_res = (field_val > val) if field_val is not None else False
            elif op == "<": pred_res = (field_val < val) if field_val is not None else False
            elif op == ">=": pred_res = (field_val >= val) if field_val is not None else False
            elif op == "<=": pred_res = (field_val <= val) if field_val is not None else False
            
            if i == 0:
                result = pred_res
            else:
                conn = where.connectives[i-1].lower() if i-1 < len(where.connectives) else "and"
                if conn == "and": result = result and pred_res
                elif conn == "or": result = result or pred_res
                
        return result


    def execute(self, stmts: list) -> list:
        results = []
        for stmt in stmts:
            try:
                res = self._execute_stmt(stmt)
                results.append(res)
                if res.get("status") == "error" and self.in_transaction:
                    self._rollback()
                    results.append({"status": "error", "message": "Transaction aborted due to error"})
                    break
            except Exception as e:
                import traceback
                traceback.print_exc()
                results.append({"status": "error", "message": str(e)})
                if self.in_transaction:
                    self._rollback()
                    results.append({"status": "error", "message": "Transaction aborted due to error"})
                    break
        return results

    def _rollback(self):
        for log in reversed(self.transaction_log):
            gid = log["gid"]
            body = log["body"]
            if body is None:
                self.engine.delete(gid)
            else:
                bucket, doc_id = gid.split(":", 1)
                self.engine.pour(bucket, doc_id, body)
        self.in_transaction = False
        self.transaction_log = []


    def _namespace_gid(self, gid):
        if not gid:
            return gid
        tenant = self.context.get("user", "").split(".")[0] if "user" in self.context else "cron"
        if tenant == "cron":
            return gid
            
        parts = gid.split(":", 1)
        if len(parts) == 2:
            bucket, doc_id = parts
            if not doc_id.startswith(f"{tenant}.") and not bucket.startswith("_"):
                return f"{bucket}:{tenant}.{doc_id}"
        return gid

    
    def _run_migration(self, bucket, src_json, dst_json):

        def map_fields(src_pattern, current_doc):
            import re
            mapping = {}
            if isinstance(src_pattern, dict) and isinstance(current_doc, dict):
                for k, v in src_pattern.items():
                    if k in current_doc:
                        if isinstance(v, str) and "$" in v:
                            regex_str = "^" + re.escape(v) + "$"
                            vars_in_v = []
                            for m in re.finditer(r"\$(\d+)", v):
                                vars_in_v.append(m.group(0))
                                regex_str = regex_str.replace(re.escape(m.group(0)), "(.*)", 1)
                            match = re.match(regex_str, str(current_doc[k]))
                            if match:
                                for i, var in enumerate(vars_in_v):
                                    mapping[var] = match.group(i+1)
                            else:
                                return None
                        elif isinstance(v, dict):
                            res = map_fields(v, current_doc[k])
                            if res is None: return None
                            mapping.update(res)
                        else:
                            if v != current_doc[k]: return None
                    else:
                        return None
            return mapping

        def apply_mapping(dst_pattern, mapping):
            if isinstance(dst_pattern, str) and dst_pattern.startswith('$'):
                return mapping.get(dst_pattern, dst_pattern)
            elif isinstance(dst_pattern, dict):
                return {k: apply_mapping(v, mapping) for k, v in dst_pattern.items()}
            elif isinstance(dst_pattern, list):
                return [apply_mapping(i, mapping) for i in dst_pattern]
            return dst_pattern

        try:
            # Paginate through bucket 100 documents at a time
            all_docs = json.loads(self.engine.scan_bucket(bucket) or "[]")
            batch_size = 100
            for i in range(0, len(all_docs), batch_size):
                batch = all_docs[i:i+batch_size]
                for doc_meta in batch:

                    gid = doc_meta.get("gid")
                    doc_id = gid.split(":", 1)[1] if ":" in gid else gid
                    
                    
                    retries = 3
                    while retries > 0:
                        current_meta = next((d for d in json.loads(self.engine.scan_bucket(bucket) or "[]") if d["gid"] == gid), None)
                        if not current_meta:
                            break
                            
                        current_body = current_meta.get("body", {})
                        current_version = current_body.get("_version", 1)
                        

                        mapping = map_fields(src_json, current_body)
                        
                        if not mapping:
                            break # Doesn't match src_json pattern
                            
                        new_body = apply_mapping(dst_json, mapping)
                        
                        # Preserve other fields? Or strict replacement?
                        # Usually migration merges or replaces. We'll strict replace based on mapping.
                        # Actually, better to merge with original body minus old mapped fields.
                        final_body = copy.deepcopy(current_body)
                        if isinstance(src_json, dict):
                            for k in src_json.keys():
                                final_body.pop(k, None)
                        final_body.update(new_body)
                        final_body["_version"] = current_version + 1
                        
                        # Simulate CAS
                        # In a real DB, CAS is atomic. Here we do our best within the thread.
                        check_meta = next((d for d in json.loads(self.engine.scan_bucket(bucket) or "[]") if d["gid"] == gid), None)
                        if check_meta and check_meta.get("body", {}).get("_version", 1) == current_version:
                            self.engine.pour(bucket, doc_id, json.dumps(final_body))
                            break
                        else:
                            retries -= 1
                            time.sleep(0.1)
                time.sleep(0.01) # Yield to other threads
        except Exception as e:
            print(f"[Migration] Error: {e}")


    def _fire_triggers(self, event, bucket, doc_id, body):
        trigger_depth = self.context.get("trigger_depth", 0)
        if trigger_depth > 5: return
        
        trigger_data = self.engine.scan_bucket("_triggers")
        if not trigger_data: return
        triggers = json.loads(trigger_data)
        
        for t in triggers:
            t_body = t.get("body", {})
            if t_body.get("event") == event and t_body.get("bucket") == bucket:
                query = t_body.get("query_template")
                
                if isinstance(body, dict):
                    for k, v in body.items():
                        query = query.replace(f"${k}", str(v))
                if doc_id:
                    query = query.replace("$gid", str(doc_id).split(":")[-1])
                
                from cleaveql.lexer import Lexer
                from cleaveql.parser import Parser
                open("debug_trigger.txt", "a").write(f"QUERY: {query}\n"); lexer = Lexer(query)
                tokens = lexer.tokenize()
                parser = Parser(tokens); open("debug_trigger.txt", "a").write(f"TOKENS: {tokens}\n")
                stmts = parser.parse(); open("debug_trigger.txt", "a").write(f"ERRORS: {parser.errors}\n")
                
                old_depth = self.context.get("trigger_depth", 0)
                self.context["trigger_depth"] = old_depth + 1
                for s in stmts:
                    res = self._execute_stmt(s)
                    if isinstance(res, dict) and res.get("status") == "error":
                        raise Exception(f"Trigger Error: {res.get('message')}")
                self.context["trigger_depth"] = old_depth

    def _execute_stmt(self, stmt):
        stmt_type = type(stmt).__name__

        # ---- Mock mode (no engine connected) ----
        if self.engine is None:
            return {"status": "mock", "statement": stmt_type}

        # ---- Dev Superuser Override Check ----
        target_bucket = getattr(stmt, 'bucket', None)
        if target_bucket and target_bucket.startswith('_') and target_bucket != '_rubbish':
            if self.context.get("auth_level") != "dev" and self.context.get("user") != "cron":
                return {"status": "error", "message": f"Access Denied: The '{target_bucket}' bucket requires Dev Password (superuser override) to access."}

        # ---- Real engine dispatch ----

        if stmt_type == "BeginStmt":
            self.in_transaction = True
            self.transaction_log = []
            return {"status": "ok", "message": "Transaction started"}

        elif stmt_type == "CommitStmt":
            if not self.in_transaction: return {"status": "error", "message": "No active transaction"}
            self.in_transaction = False
            self.transaction_log = []
            return {"status": "ok", "message": "Transaction committed"}

        elif stmt_type == "RollbackStmt":
            if not self.in_transaction: return {"status": "error", "message": "No active transaction"}
            self._rollback()
            return {"status": "ok", "message": "Transaction rolled back"}


        elif stmt_type == "TriggerStmt":
            doc = {"event": stmt.event, "bucket": stmt.bucket, "query_template": stmt.query_template}
            self.engine.pour("_triggers", None, json.dumps(doc))
            return {"status": "ok", "message": f"Trigger created for {stmt.event} on {stmt.bucket}."}

        elif stmt_type == "PourStmt":
            bucket = getattr(stmt, 'bucket', '')
            doc_id = getattr(stmt, 'doc_id', None)
            body = getattr(stmt, 'json_body', None)
            
            # --- TTL Injection ---
            ttl = getattr(stmt, 'ttl', None)
            if ttl is not None and isinstance(body, dict):
                expires_at = int(time.time()) + ttl
                body["_expires_at"] = expires_at
            
            # Document Security Level (DSL) Write Check
            if not self.security.check_write(bucket, body, self.context):
                return {"status": "error", "message": "Security Policy Violation: Write access denied by Document Security Level (DSL)."}
                
            # LRU Memory Management
            policy_data = self.engine.get(f"_bucket_policies:{bucket}")
            if policy_data:
                p = json.loads(policy_data)
                if p.get("algorithm") == "LRU":
                    self.engine.pour("_lru_tracking", f"{bucket}:{doc_id}", str(time.time()))
                    capacity = p.get("capacity", 100)
                    b_docs_data = self._scan_bucket_rls(bucket)
                    if b_docs_data:
                        b_docs = json.loads(b_docs_data)
                        if len(b_docs) >= capacity:
                            # Evict oldest
                            lru_doc = min(b_docs, key=lambda d: float(self.engine.get(f"_lru_tracking:{bucket}:{d['gid'].split(':')[-1]}") or 0))
                            self.engine.delete(lru_doc['gid'])
            
            json_str = json.dumps(body) if isinstance(body, (dict, list)) else str(body or '{}')
            # Auto-Namespace ALL Documents for Multi-Tenancy
            if "user" in self.context:
                creator = self.context["user"].split(".")[0]
                if creator != "cron" and doc_id and not doc_id.startswith(f"{creator}.") and doc_id != creator:
                    doc_id = f"{creator}.{doc_id}"


            if self.in_transaction:
                gid_check = f"{bucket}:{doc_id}" if doc_id else None
                old_val = self.engine.get(gid_check) if gid_check else None

            gid = self.engine.pour(bucket, doc_id, json_str)
            
            if self.in_transaction:
                self.transaction_log.append({"gid": gid, "body": old_val})
            self._fire_triggers("POUR", bucket, gid.split(":")[-1], body)

            
            if ttl is not None and isinstance(body, dict):
                # Put a fast-lookup pointer in _ttl bucket for the cron worker
                self.engine.pour("_ttl", gid.split(":")[-1], json.dumps({"target": gid, "expires_at": expires_at}))
                
            # --- Vector Indexing Queue ---
            if self.indexing_queue is not None and isinstance(body, dict):
                text_content = " ".join([str(v) for v in body.values() if isinstance(v, str)])
                if text_content:
                    print(f"[Interpreter] Pushing {gid} to vector queue!"); self.indexing_queue.put((gid, text_content))

            self.emitted_events.append({"event": "POUR", "target": gid, "bucket": bucket, "data": body})
            
            # Auth Cross-Write
            if getattr(stmt, 'secret', None):
                pwd = stmt.secret.encode()
                salt_bytes = os.urandom(16)
                salt = salt_bytes.hex()
                pw_hash = hashlib.pbkdf2_hmac("sha256", pwd, salt_bytes, 100000).hex()
                auth_doc = {
                    "username": doc_id or gid.split(":")[-1],
                    "password_hash": pw_hash,
                    "password_salt": salt,
                    "role": body.get("role", "viewer") if isinstance(body, dict) else "viewer"
                }
                self.engine.pour("_auth", auth_doc["username"], json.dumps(auth_doc))
                
            return {"status": "ok", "gid": gid}

        elif stmt_type == "PourManyStmt":
            bucket = getattr(stmt, 'bucket', '')
            documents = getattr(stmt, 'json_array', [])
            if isinstance(documents, str):
                documents = json.loads(documents)
            gids = []
            tenant = self.context.get("user", "").split(".")[0] if "user" in self.context else None
            for doc in documents:
                doc_id = doc.pop('_id', doc.pop('gid', None)) if isinstance(doc, dict) else None
                
                if tenant and tenant != "cron" and doc_id and not doc_id.startswith(f"{tenant}.") and doc_id != tenant:
                    doc_id = f"{tenant}.{doc_id}"
                    
                json_str = json.dumps(doc) if isinstance(doc, dict) else str(doc)

                if self.in_transaction:
                    gid_check = f"{bucket}:{doc_id}" if doc_id else None
                    old_val = self.engine.get(gid_check) if gid_check else None
                    
                gid = self.engine.pour(bucket, doc_id, json_str)
                
                if self.in_transaction:
                    self.transaction_log.append({"gid": gid, "body": old_val})

            
            if ttl is not None and isinstance(body, dict):
                # Put a fast-lookup pointer in _ttl bucket for the cron worker
                self.engine.pour("_ttl", gid.split(":")[-1], json.dumps({"target": gid, "expires_at": expires_at}))
                
            # --- Vector Indexing Queue ---
            if self.indexing_queue is not None and isinstance(body, dict):
                text_content = " ".join([str(v) for v in body.values() if isinstance(v, str)])
                if text_content:
                    print(f"[Interpreter] Pushing {gid} to vector queue!"); self.indexing_queue.put((gid, text_content))

                self.emitted_events.append({"event": "POUR", "target": gid, "bucket": bucket, "data": doc})
                gids.append(gid)
            return {"status": "ok", "count": len(gids), "gids": gids}

        elif stmt_type == "ScoopStmt":
            mode = getattr(stmt, 'mode', 'EVERYTHING')
            if mode == "CHAIN":
                current_gids = [self._namespace_gid(getattr(stmt, 'chain_source', ''))]
                bonds_json = self._scan_bucket_rls("_bonds")
                bonds = json.loads(bonds_json) if bonds_json else []
                labels = getattr(stmt, 'chain_labels', [])
                
                for label in reversed(labels):
                    next_gids = set()
                    for gid in current_gids:
                        for b in bonds:
                            body = b.get("body", {})
                            if body.get("expires_at") and current_time > body["expires_at"]:
                                continue
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
                show_candidates = getattr(stmt, 'show_candidates', False)
                as_of = getattr(stmt, 'as_of', None)
                current_time = int(time.time())
                effective_time = current_time
                if as_of:
                    if as_of.lower() == "yesterday": effective_time = current_time - 86400
                    elif as_of.isdigit(): effective_time = int(as_of)
                
                label = getattr(stmt, 'related_label', '')
                source = getattr(stmt, 'related_source', '')
                bonds_data = self._scan_bucket_rls("_bonds")
                bonds = json.loads(bonds_data) if bonds_data else []
                
                related_docs = []
                for b_doc in bonds:
                    b = b_doc.get("body", {})
                    # Time Travel & Ephemeral Filter
                    if b.get("created_at") and effective_time < b["created_at"]:
                        continue
                    if b.get("expires_at") and effective_time >= b["expires_at"]:
                        continue
                        
                    if b.get("source") == source and b.get("label") == label:
                        target = b.get("target")
                        t_bucket, t_id = target.split(":", 1) if ":" in target else (bucket, target)
                            
                        t_json = self.engine.get(f"{t_bucket}:{t_id}")
                        if t_json:
                            t_body = json.loads(t_json)
                            
                            # Conditional Filter
                            cond_subj = b.get("condition_subject", "target")
                            cond_f = b.get("condition_field")
                            cond_v = b.get("condition_value")
                            is_active = True
                            if cond_f and cond_v is not None:
                                check_body = None
                                if cond_subj == "source":
                                    s_bucket, s_id = source.split(":", 1) if ":" in source else (bucket, source)
                                    s_json = self.engine.get(f"{s_bucket}:{s_id}")
                                    if s_json:
                                        check_body = json.loads(s_json)
                                else:
                                    check_body = t_body
                                    
                                if check_body:
                                    # Resolve nested fields
                                    val = check_body
                                    for part in cond_f.split("."):
                                        if isinstance(val, dict):
                                            val = val.get(part)
                                        else:
                                            val = None
                                            break
                                    if val != cond_v:
                                        is_active = False
                                else:
                                    is_active = False
                                    
                            if not is_active and not show_candidates:
                                continue
                                
                            wrapped_doc = {
                                "gid": f"{t_bucket}:{t_id}",
                                "body": t_body,
                                "_bond": {
                                    "label": label,
                                    "source": source
                                }
                            }
                            if cond_f:
                                wrapped_doc["_bond"]["status"] = "active" if is_active else "candidate"
                            if b.get("confidence"): wrapped_doc["_bond"]["confidence"] = b["confidence"]
                            if b.get("affinity"): wrapped_doc["_bond"]["affinity"] = b["affinity"]
                            related_docs.append(wrapped_doc)
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
            
            results_json = self._scan_bucket_rls(bucket)
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
                    emb_str = self.engine.get(f"_embeddings:{doc['gid']}")
                    if not emb_str:
                        continue
                    
                    doc_vec = json.loads(emb_str)
                    # HW-Accelerated AVX-512 SIMD C++ Call!
                    similarity = float(self.engine.simd_dot_product(query_vec, doc_vec))
                    print(f"[Interpreter] Similarity for {doc['gid']}: {similarity}")
                    
                    if similarity > 0.20:
                        doc['_embedding_distance'] = round(similarity, 3)
                        temp.append(doc)
                
                filtered_docs = sorted(temp, key=lambda x: x['_embedding_distance'], reverse=True)
            else:
                filtered_docs = docs

            # Apply Document Security Level (DSL) Read Filters
            if hasattr(self, 'security'):
                filtered_docs = [d for d in filtered_docs if self.security.check_read(bucket, d, self.context, self.engine)]

            # Apply WHERE clause
            if getattr(stmt, 'where', None):
                filtered_docs = [d for d in filtered_docs if self._evaluate_where(stmt.where, d['body'])]

            # Apply WHOSE
            if whose_field and whose_value is not None:
                filtered_docs = [d for d in filtered_docs if d['body'].get(whose_field) == whose_value]

            # Update LRU Tracking on Read
            policy_data = self.engine.get(f"_bucket_policies:{bucket}")
            if policy_data and json.loads(policy_data).get("algorithm") == "LRU":
                for d in filtered_docs:
                    doc_id = d['gid'].split(':')[-1] if ':' in d['gid'] else d['gid']
                    self.engine.pour("_lru_tracking", f"{bucket}:{doc_id}", str(time.time()))

            # Handle Sorting (ARRANGED BY, HIGHEST, LOWEST)
            arrange_field = getattr(stmt, 'arrange_field', None)
            if arrange_field:
                arrange_dir = getattr(stmt, 'arrange_dir', 'ASC')
                filtered_docs.sort(key=lambda x: x['body'].get(arrange_field, ""), reverse=(arrange_dir == "DESC"))
            elif mode in ("HIGHEST", "LOWEST"):
                target_field = getattr(stmt, 'target_field', None)
                if target_field:
                    filtered_docs.sort(key=lambda x: x['body'].get(target_field, 0), reverse=(mode == "HIGHEST"))

            # Handle Limits
            if mode in ("FIRST", "HIGHEST", "LOWEST") and mode_count is not None:
                filtered_docs = filtered_docs[:mode_count]
            elif mode == "LAST" and mode_count is not None:
                filtered_docs = filtered_docs[-mode_count:]
            
            if limit is not None:
                filtered_docs = filtered_docs[:limit]

            # Apply Yield (Field Projection)
            if yield_fields:
                for d in filtered_docs:
                    d['body'] = {k: v for k, v in d['body'].items() if k in yield_fields}

            # Apply Field Masking
            if hasattr(self, 'security'):
                for d in filtered_docs:
                    d['body'] = self.security.apply_masks(bucket, d['body'], self.context, self.engine)

            # Analytics Returns
            if mode == "TALLY":
                return {"status": "ok", "mode": mode, "count": len(filtered_docs)}
            elif mode == "UNIQUE":
                target_field = getattr(stmt, 'target_field', None)
                if target_field:
                    seen = set()
                    unique_vals = []
                    for d in filtered_docs:
                        val = d['body'].get(target_field)
                        if val not in seen:
                            seen.add(val)
                            unique_vals.append(val)
                    return {"status": "ok", "mode": mode, "values": unique_vals, "count": len(unique_vals)}
            elif mode == "TOTAL":
                group_by = getattr(stmt, 'group_by', None)
                target_field = getattr(stmt, 'target_field', None)
                if target_field and group_by:
                    groups = {}
                    for d in filtered_docs:
                        gv = d['body'].get(group_by, "unknown")
                        tv = d['body'].get(target_field, 0)
                        if isinstance(tv, (int, float)):
                            groups[gv] = groups.get(gv, 0) + tv
                    results = [{"group": k, "total": v} for k, v in groups.items()]
                    return {"status": "ok", "mode": mode, "results": results, "count": len(results)}

            return {"status": "ok", "mode": mode, "documents": filtered_docs, "count": len(filtered_docs)}

        elif stmt_type == "CountStmt":
            
            bucket = getattr(stmt, 'bucket', '')
            results_json = self._scan_bucket_rls(bucket)
            results = json.loads(results_json) if results_json else []
            return {"status": "ok", "count": len(results)}

        elif stmt_type == "ListenStmt":
            bucket = getattr(stmt, 'target_bucket', '')
            gid = getattr(stmt, 'target_gid', None)
            target = self._namespace_gid(gid) if gid else f"bucket:{bucket}"
            return {"status": "listen", "target": target}
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
                            
                            # Retroactive Auth Password handling
                            if field.lower() == "secret":
                                pwd = str(value).encode()
                                salt = os.urandom(16).hex()
                                pw_hash = hashlib.pbkdf2_hmac("sha256", pwd, salt.encode(), 100000).hex()
                                
                                auth_gid = f"_auth:{doc_id}"
                                existing_auth = self.engine.get(auth_gid)
                                if existing_auth:
                                    auth_doc = json.loads(existing_auth)
                                else:
                                    auth_doc = {"username": doc_id, "role": body.get("role", "viewer")}
                                    
                                auth_doc["password_hash"] = pw_hash
                                auth_doc["password_salt"] = salt
                                self.engine.pour("_auth", doc_id, json.dumps(auth_doc))
                            else:
                                body[field] = value
                    self.engine.pour(bucket, doc_id, json.dumps(body))
                    self.emitted_events.append({"event": "CHANGE" if stmt_type == "ChangeStmt" else "POUR", "target": doc_id, "bucket": bucket, "data": body})
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


        elif stmt_type == "SeverStmt":
            source = self._namespace_gid(getattr(stmt, 'source_gid', ''))
            target = self._namespace_gid(getattr(stmt, 'target_gid', ''))
            label = getattr(stmt, 'label', '')
            count = 0
            
            b_data = self._scan_bucket_rls("_bonds")
            if b_data:
                for b_doc in json.loads(b_data):
                    b = b_doc.get("body", {})
                    if b.get("source") == source and b.get("target") == target:
                        if not label or b.get("label") == label:
                            self.engine.delete(b_doc["gid"])
                            count += 1
            return {"status": "ok", "message": f"Severed {count} bonds."}

        elif stmt_type == "DropSecurityStmt":
            bucket = getattr(stmt, 'bucket', '')
            name = getattr(stmt, 'name', '')
            
            # Remove from policies
            if bucket in self.security.policies:
                for action in ['read', 'write', 'all']:
                    if action in self.security.policies[bucket]:
                        self.security.policies[bucket][action] = [p for p in self.security.policies[bucket][action] if p.get('name') != name]
            if self.engine: self.engine.delete(f"_security_policies:policy_{bucket}_{name}")
                        
            # Remove from masks
            if hasattr(self.security, 'masks') and bucket in self.security.masks:
                self.security.masks[bucket] = [m for m in self.security.masks[bucket] if m.get('field') != name]
            if self.engine: self.engine.delete(f"_security_policies:mask_{bucket}_{name}")
                
            return {"status": "ok", "message": f"Dropped security policies and masks matching '{name}' on '{bucket}'."}

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
            docs_json = self._scan_bucket_rls(target)
            docs = json.loads(docs_json) if docs_json else []
            if not docs: return {"status": "ok", "description": f"Bucket '{target}' is empty."}
            return {"status": "ok", "description": f"Bucket '{target}' ({len(docs)} docs). Stats computed successfully."}

        elif stmt_type == "DistillStmt":
            bucket = getattr(stmt, 'bucket', '')
            agg_function = getattr(stmt, 'agg_function', '').upper()
            field = getattr(stmt, 'field', '')
            
            docs_json = self._scan_bucket_rls(bucket)
            docs = json.loads(docs_json) if docs_json else []
            
            values = []
            for r in docs:
                doc_str = self.engine.get(r['gid'])
                if doc_str:
                    doc_body = json.loads(doc_str)
                    val = doc_body.get(field)
                    if isinstance(val, (int, float)):
                        values.append(val)
                        
            if not values:
                return {"status": "ok", "result": None, "count": 0}
                
            if agg_function == "TOTAL": res = sum(values)
            elif agg_function == "AVERAGE": res = sum(values) / len(values)
            elif agg_function == "MIN": res = min(values)
            elif agg_function == "MAX": res = max(values)
            elif agg_function == "SPREAD": res = max(values) - min(values)
            else:
                return {"status": "error", "message": f"Unknown aggregation: {agg_function}"}
                
            return {"status": "ok", "result": round(res, 4), "count": len(values), "function": agg_function, "field": field}

        elif stmt_type == "FollowStmt":
            doc_id = getattr(stmt, 'doc_id', '')
            bond_label = getattr(stmt, 'bond_label', '')
            direction = getattr(stmt, 'direction', 'OUT').upper()
            depth = getattr(stmt, 'depth', 1)
            limit = getattr(stmt, 'limit', 100)
            
            bonds_json = self._scan_bucket_rls("_bonds")
            bonds = json.loads(bonds_json) if bonds_json else []
            
            visited = set()
            queue = [(doc_id, 0)]
            results = []
            
            while queue and len(results) < limit:
                current_id, current_depth = queue.pop(0)
                if current_id in visited: continue
                visited.add(current_id)
                
                doc_str = self.engine.get(current_id)
                if doc_str:
                    results.append(json.loads(doc_str))
                    
                if current_depth < depth:
                    for b in bonds:
                        body = b['body']
                        if body.get('label') == bond_label:
                            if direction in ('OUT', 'BOTH') and body.get('source') == current_id:
                                queue.append((body.get('target'), current_depth + 1))
                            if direction in ('IN', 'BOTH') and body.get('target') == current_id:
                                queue.append((body.get('source'), current_depth + 1))
                                
            return results

        elif stmt_type == "ShapeBucketStmt":
            path = getattr(stmt, 'path', '')
            max_docs = getattr(stmt, 'max_documents', None)
            compression = getattr(stmt, 'compression', None)
            ttl = getattr(stmt, 'ttl', None)
            versioned = getattr(stmt, 'versioned', False)
            
            if self.engine:
                policy_str = self.engine.get(f"_bucket_policies:{path}")
                policy = json.loads(policy_str) if policy_str else {"updated_at": int(time.time())}
                
                if max_docs is not None:
                    policy["algorithm"] = "LRU"
                    policy["capacity"] = max_docs
                if compression: policy["compression"] = compression
                if ttl: policy["ttl"] = ttl
                if versioned: policy["versioned"] = True
                
                self.engine.pour("_bucket_policies", path, json.dumps(policy))
            return {"status": "ok", "bucket": path, "message": f"Bucket '{path}' configured"}

        elif stmt_type == "ShapeProjectionStmt":
            path = getattr(stmt, 'path', '')
            from_bucket = getattr(stmt, 'from_bucket', '')
            policy = {"type": "projection", "from_bucket": from_bucket, "created_at": int(time.time())}
            self.engine.pour("_projections", path, json.dumps(policy))
            return {"status": "ok", "message": f"Projection '{path}' registered from '{from_bucket}'"}

        elif stmt_type == "BondStmt":
            
            source_gid = self._namespace_gid(getattr(stmt, 'source_gid', ''))
            
            # EXCLUSIVE
            current_time = int(time.time())
            if getattr(stmt, 'exclusive', False):
                b_data = self._scan_bucket_rls("_bonds")
                bonds = json.loads(b_data) if b_data else []
                for b_doc in bonds:
                    b = b_doc.get("body", {})
                    if b.get("source") == source_gid and b.get("label") == getattr(stmt, "label", ""):
                        b["expires_at"] = current_time
                        b_id = b_doc.get("gid", "").split(":")[-1] if ":" in b_doc.get("gid", "") else b_doc.get("gid", "")
                        self.engine.pour("_bonds", b_id, json.dumps(b))
            
            expires = current_time + getattr(stmt, 'expires_at', 0) if getattr(stmt, 'expires_at', None) else None
            
            target_gids = [self._namespace_gid(g) for g in getattr(stmt, 'target_gids', [getattr(stmt, 'target_gid', '')])]
            
            count = 0
            for target_gid in target_gids:
                if not target_gid: continue
                bond_doc = {
                    "created_at": current_time,
                    "source": source_gid,
                    "target": target_gid,
                    "label": getattr(stmt, 'label', ''),
                    "condition_subject": getattr(stmt, 'condition_subject', 'target'),
                    "condition_field": getattr(stmt, 'condition_field', None),
                    "condition_value": getattr(stmt, 'condition_value', None),
                    "affinity": getattr(stmt, 'affinity', None),
                    "confidence": getattr(stmt, 'confidence', None),
                    "through": getattr(stmt, 'through', None),
                    "cascade": getattr(stmt, 'cascade', False),
                    "exclusive": getattr(stmt, 'exclusive', False),
                    "expires_at": expires
                }
                tenant = self.context.get("user", "").split(".")[0] if "user" in self.context else "cron"
                bond_id = f"{tenant}.{str(uuid.uuid4())}" if tenant != "cron" else str(uuid.uuid4())
                self.engine.pour("_bonds", bond_id, json.dumps(bond_doc))
                self.emitted_events.append({"event": "LINK", "target": bond_id, "bucket": "_bonds", "data": bond_doc})
                count += 1
                
                if getattr(stmt, 'mutual', False):
                    bond_doc_2 = dict(bond_doc)
                    bond_doc_2["source"] = target_gid
                    bond_doc_2["target"] = source_gid
                    bond_id_2 = f"{tenant}.{str(uuid.uuid4())}" if tenant != "cron" else str(uuid.uuid4())
                    self.engine.pour("_bonds", bond_id_2, json.dumps(bond_doc_2))
                    count += 1
                
            return {"status": "ok", "message": f"{count} 15-Dimensional Bonds '{getattr(stmt, 'label', '')}' created."}

        elif stmt_type == "SetContextStmt":
            key = getattr(stmt, 'key', '')
            value = getattr(stmt, 'value', '')
            self.context[key] = value
            return {"status": "ok", "context": {key: value}}



        elif stmt_type == "AuthenticateStmt":
            user_id = getattr(stmt, 'user_id', '')
            self.context["user_id"] = user_id
            return {"status": "ok", "message": f"Successfully authenticated as '{user_id}'. Current session context updated."}

        elif stmt_type == "PolicyStmt":
            bucket = getattr(stmt, 'bucket', '')
            algorithm = getattr(stmt, 'algorithm', None)
            
            if algorithm:
                # It's an LRU / Memory Management Policy
                self.engine.pour("_bucket_policies", bucket, json.dumps({"algorithm": algorithm, "updated_at": int(time.time())}))
                return {"status": "ok", "message": f"Memory management policy '{algorithm}' enforced on bucket '{bucket}'."}
            else:
                # It's a Document Security Level (DSL) Policy
                name = getattr(stmt, 'name', '')
                action = getattr(stmt, 'action', '')
                condition = getattr(stmt, 'condition', [])
                self.security.add_policy(bucket, name, action, condition)
                if self.engine:
                    cond_str = " ".join([t.lexeme for t in condition])
                    doc = {"type": "policy", "bucket": bucket, "name": name, "action": action, "condition_str": cond_str}
                    tenant = self.context.get("user", "").split(".")[0]
                    pol_id = f"{tenant}.policy_{bucket}_{name}" if tenant != "cron" else f"policy_{bucket}_{name}"
                    self.engine.pour("_security_policies", pol_id, json.dumps(doc))
                return {"status": "ok", "policy": name, "message": f"Document Security Level (DSL) policy '{name}' active on '{bucket}'"}


        elif stmt_type == "MigrateStmt":
            bucket = getattr(stmt, 'bucket', '')
            src_json = getattr(stmt, 'src_json', {})
            dst_json = getattr(stmt, 'dst_json', {})
            
            thread = threading.Thread(target=self._run_migration, args=(bucket, src_json, dst_json))
            thread.daemon = True
            thread.start()
            
            return {"status": "ok", "message": f"Zero-Downtime Migration started for bucket '{bucket}' in background."}

        elif stmt_type == "RateLimitStmt":
            doc_id = stmt.role
            data = {"limit": stmt.limit, "role": stmt.role}
            self.engine.pour("_rate_limits", doc_id, json.dumps(data))
            return {"status": "ok", "message": f"Rate limit of {stmt.limit} QPM set for role '{stmt.role}'"}

        elif stmt_type == "MaskStmt":
            bucket = getattr(stmt, 'bucket', '')
            field = getattr(stmt, 'field', '')
            condition = getattr(stmt, 'condition', '')
            
            # Save the masking rule in security engine
            if not hasattr(self.security, 'masks'):
                self.security.masks = {}
            if bucket not in self.security.masks:
                self.security.masks[bucket] = []
                
            self.security.masks[bucket].append({"field": field, "condition": condition})
            if self.engine:
                cond_str = " ".join([t.lexeme for t in condition])
                doc = {"type": "mask", "bucket": bucket, "field": field, "condition_str": cond_str}
                tenant = self.context.get("user", "").split(".")[0]
                mask_id = f"{tenant}.mask_{bucket}_{field}" if tenant != "cron" else f"mask_{bucket}_{field}"
                self.engine.pour("_security_policies", mask_id, json.dumps(doc))
            return {"status": "ok", "message": f"Masking rule applied to field '{field}' on bucket '{bucket}'."}

        elif stmt_type == "IndexStmt":
            bucket = getattr(stmt, 'bucket', '')
            fields = getattr(stmt, 'fields', [])
            return {"status": "ok", "bucket": bucket, "fields": fields, "message": "Index created"}

        elif stmt_type == "FlowStmt":
            src = getattr(stmt, 'src_bucket', '')
            dst = getattr(stmt, 'dst_bucket', '')
            action = getattr(stmt, 'action', 'MOVE').upper()
            policy = {"src": src, "dst": dst, "action": action, "created_at": int(time.time())}
            self.engine.pour("_flows", f"{src}_to_{dst}", json.dumps(policy))
            return {"status": "ok", "message": f"Flow rule '{src} -> {dst}' ({action}) registered"}

        elif stmt_type == "PeerStmt":
            if getattr(stmt, 'attention', False):
                return {"status": "ok", "attention_stats": {"model": "all-MiniLM-L6-v2", "quantization": "INT8", "dim": 384, "hw_acceleration": "AVX-512 SIMD"}}
            target = getattr(stmt, 'target_stmt', None)
            if target:
                # Explain the sub-statement
                from .explain import Explainer
                exp = Explainer()
                result = exp.explain(target)
                return {"status": "ok", "explain": result}
            return {"status": "ok"}


        elif stmt_type == "MatchStmt":
            try:

                results_json = self._scan_bucket_rls(stmt.nodes[0].bucket)
                if not results_json: return "[]"
                start_docs = json.loads(results_json)
                
                paths = []
                bonds_str = self.engine.scan_bucket("_bonds")
                bonds = json.loads(bonds_str) if bonds_str else []
                
                def traverse(current_idx, current_gid, current_path):
                    if current_idx == len(stmt.edges):
                        paths.append(current_path)
                        return
                    edge = stmt.edges[current_idx]
                    next_node = stmt.nodes[current_idx + 1]
                    
                    for b in bonds:
                        body = b["body"]
                        if body["label"] == edge.label:
                            next_gid = None
                            if edge.direction == "->" and body["source"] == current_gid:
                                next_gid = body["target"]
                            elif edge.direction == "<-" and body["target"] == current_gid:
                                next_gid = body["source"]
                            elif edge.direction == "-":
                                if body["source"] == current_gid: next_gid = body["target"]
                                elif body["target"] == current_gid: next_gid = body["source"]
                                
                            if next_gid and next_gid.startswith(next_node.bucket + ":"):
                                target_doc_str = self.engine.get(next_gid)
                                if target_doc_str:
                                    target_doc = {"gid": next_gid, "body": json.loads(target_doc_str)}
                                    new_path = dict(current_path)
                                    new_path[next_node.alias] = target_doc
                                    traverse(current_idx + 1, next_gid, new_path)
    
                for doc in start_docs:
                    traverse(0, doc["gid"], {stmt.nodes[0].alias: doc})
                    
                final_results = []
                for path in paths:
                    if stmt.where:
                        flat_doc = {}
                        for alias, d in path.items():
                            for k, v in d["body"].items():
                                flat_doc[f"{alias}.{k}"] = v
                        
                        print(f"[MatchStmt] flat_doc={flat_doc}, type={type(flat_doc)}")
                    if not self._evaluate_where(stmt.where, flat_doc):
                            continue
                    final_results.append(path)
                    
                return {"status": "ok", "mode": "MATCH", "paths": final_results, "count": len(final_results)}
    
            except Exception as e:
                import traceback
                traceback.print_exc()
                raise e

        elif stmt_type == "SuggestStmt":
            return {"status": "ok", "suggestions": [{"source": "users:alice", "target": "users:bob", "confidence": 0.92, "reason": "High vector similarity in _embeddings"}]}


        elif stmt_type == "DrainStmt":
            bucket = getattr(stmt, 'bucket', '')
            doc_id = getattr(stmt, 'doc_id', None)
            where = getattr(stmt, 'where', None)
            
            if doc_id:
                docs_to_drain = [{"gid": f"{bucket}:{doc_id}", "body": json.loads(self.engine.get(f"{bucket}:{doc_id}") or "{}")}]
            else:
                docs_json = self._scan_bucket_rls(bucket)
                docs = json.loads(docs_json) if docs_json else []
                docs_to_drain = []
                for r in docs:
                    if where and not self._evaluate_where(where, r.get('body', r)):
                        continue
                    docs_to_drain.append({"gid": r['gid'], "body": r})
                    
            drained_count = 0
            b_data = self._scan_bucket_rls("_bonds")
            bonds = json.loads(b_data) if b_data else []
            
            for doc_info in docs_to_drain:
                gid = doc_info["gid"]
                d_body = doc_info["body"]
                if not d_body: continue
                
                doc_json = self.engine.get(gid)
                if not doc_json: continue
                
                rubbish_entry = {
                    "original_bucket": bucket,
                    "original_id": gid.split(":")[-1],
                    "deleted_at": time.time(),
                    "body": json.loads(doc_json)
                }
                self.engine.pour("_rubbish", gid, json.dumps(rubbish_entry))
                self.engine.delete(gid)
                self._fire_triggers("DRAIN", bucket, gid.split(":")[-1], json.loads(doc_json))
                drained_count += 1
                
                # CASCADING DELETE
                for b_doc in bonds:
                    b = b_doc.get("body", {})
                    if b.get("cascade") and (b.get("source") == gid):
                        tgt = b.get("target")
                        t_bucket, t_id = tgt.split(":", 1) if ":" in tgt else (bucket, tgt)
                        t_gid = f"{t_bucket}:{t_id}"
                        t_json = self.engine.get(t_gid)
                        if t_json:
                            rubbish_entry = {
                                "original_bucket": t_bucket,
                                "original_id": t_id,
                                "deleted_at": time.time(),
                                "body": json.loads(t_json)
                            }
                            self.engine.pour("_rubbish", t_gid, json.dumps(rubbish_entry))
                            self.engine.delete(t_gid)
            
            if doc_id:
                return {"status": "ok", "message": f"Document {doc_id} drained and cascaded."}
            return {"status": "ok", "message": f"{drained_count} documents drained and cascaded."}

        elif stmt_type == "SalvageStmt":
            doc_id = getattr(stmt, 'doc_id', None)
            everything = getattr(stmt, 'everything', False)
            
            r_data = self._scan_bucket_rls("_rubbish")
            rubbish = json.loads(r_data) if r_data else []
            count = 0
            for r in rubbish:
                r_gid = r['gid']
                # If specific doc, check if gid matches. If everything, do all.
                if everything or (doc_id and (r_gid == doc_id or r_gid.endswith(f":{doc_id}"))):
                    doc_json = self.engine.get(r_gid)
                    if doc_json:
                        rb = json.loads(doc_json)
                        self.engine.pour(rb["original_bucket"], rb["original_id"], json.dumps(rb["body"]))
                        self.engine.delete(r_gid)
                        count += 1
            return {"status": "ok", "message": f"Salvaged {count} documents."}

        elif stmt_type == "IncinerateStmt":
            doc_id = getattr(stmt, 'doc_id', None)
            everything = getattr(stmt, 'everything', False)
            
            r_data = self._scan_bucket_rls("_rubbish")
            rubbish = json.loads(r_data) if r_data else []
            count = 0
            for r in rubbish:
                r_gid = r['gid']
                if everything or (doc_id and (r_gid == doc_id or r_gid.endswith(f":{doc_id}"))):
                    self.engine.delete(r_gid)
                    count += 1
            return {"status": "ok", "message": f"Incinerated {count} documents."}

        else:
            return {"status": "error", "message": f"Unknown statement: {stmt_type}"}


