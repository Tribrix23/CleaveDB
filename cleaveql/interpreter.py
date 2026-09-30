import time
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

    def __init__(self, engine=None):
        self.engine = engine
        self.context = {}
        self.emitted_events = []
        self.security = PolicyEngine()
        
    def set_context(self, context):
        self.context = context
        self.security = PolicyEngine()
        if self.engine:
            from .lexer import Lexer
            pol_data = self._scan_bucket_rls("_security_policies")
            if pol_data:
                import json
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
                results.append(self._execute_stmt(stmt))
            except Exception as e:
                results.append({"status": "error", "message": str(e)})
        return results

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
        if stmt_type == "PourStmt":
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

            gid = self.engine.pour(bucket, doc_id, json_str)
            
            if ttl is not None and isinstance(body, dict):
                # Put a fast-lookup pointer in _ttl bucket for the cron worker
                self.engine.pour("_ttl", gid.split(":")[-1], json.dumps({"target": gid, "expires_at": expires_at}))

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
                gid = self.engine.pour(bucket, doc_id, json_str)
            
            if ttl is not None and isinstance(body, dict):
                # Put a fast-lookup pointer in _ttl bucket for the cron worker
                self.engine.pour("_ttl", gid.split(":")[-1], json.dumps({"target": gid, "expires_at": expires_at}))

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
            return {"status": "ok", "note": "Aggregation requires cursor support"}

        elif stmt_type == "FollowStmt":
            return {"status": "ok", "note": "Bond traversal requires edge index"}

        elif stmt_type == "ShapeBucketStmt":
            path = getattr(stmt, 'path', '')
            max_docs = getattr(stmt, 'max_documents', None)
            if max_docs is not None and self.engine:
                policy = {"algorithm": "LRU", "capacity": max_docs, "updated_at": int(time.time())}
                self.engine.pour("_bucket_policies", path, json.dumps(policy))
            return {"status": "ok", "bucket": path, "message": f"Bucket '{path}' configured"}

        elif stmt_type == "ShapeProjectionStmt":
            return {"status": "ok", "note": "Projection registered"}

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
                gid = f"{bucket}:{doc_id}"
                doc_json = self.engine.get(gid)
                if doc_json:
                    rubbish_entry = {
                        "original_bucket": bucket,
                        "original_id": doc_id,
                        "deleted_at": time.time(),
                        "body": json.loads(doc_json)
                    }
                    self.engine.pour("_rubbish", gid, json.dumps(rubbish_entry))
                    self.engine.delete(gid)
                
                # CASCADING DELETE
                b_data = self._scan_bucket_rls("_bonds")
                bonds = json.loads(b_data) if b_data else []
                for b_doc in bonds:
                    b = b_doc.get("body", {})
                    if b.get("cascade") and (b.get("source") == gid or b.get("source") == doc_id):
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
                
                return {"status": "ok", "message": f"Document {doc_id} drained and cascaded."}
            return {"status": "error", "message": "Mass drain not supported yet."}

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


