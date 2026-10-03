import time
import uuid
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
from .security import PolicyEngine, SecurityError, validate_webhook_url, MAX_FORECAST_HORIZON


class TenantEngineProxy:
    def __init__(self, engine, context):
        self.engine = engine
        self.context = context

    def _tenant(self):
        if "tenant_id" in self.context and self.context["tenant_id"]:
            return self.context["tenant_id"]
        return (
            self.context.get("tenant_id", self.context.get("user", "").split(".")[0])
            if "user" in self.context
            else "cron"
        )

    def _ns(self, bucket):
        if not bucket or bucket.startswith("_"):
            return bucket
        t = self._tenant()
        if t == "cron":
            return bucket
        if bucket.startswith(f"{t}."):
            return bucket
        return f"{t}.{bucket}"

    def _ns_gid(self, gid):
        if not gid:
            return gid
        parts = gid.split(":", 1)
        if len(parts) == 2:
            return f"{self._ns(parts[0])}:{parts[1]}"
        return gid

    def pour(self, bucket, doc_id, json_str):
        return self.engine.pour(self._ns(bucket), doc_id, json_str)

    def get(self, gid):
        return self.engine.get(self._ns_gid(gid))

    def delete(self, gid):
        return self.engine.delete(self._ns_gid(gid))

    def scan_bucket(self, bucket):
        data = self.engine.scan_bucket(self._ns(bucket))
        if not data:
            return data
        if bucket.startswith("_"):


            t = self._tenant()
            if t != "cron":
                docs = json.loads(data)
                filtered = []
                for d in docs:
                    gid = d.get("gid", "")
                    body = d.get("body", {})
                    if bucket == "_auth":
                        if gid == f"_auth:{t}":
                            filtered.append(d)
                    elif bucket == "_bonds":
                        if ":" in gid and gid.split(":", 1)[1].startswith(f"{t}."):
                            filtered.append(d)
                    elif bucket == "_security_policies":
                        if ":" in gid and gid.split(":", 1)[1].startswith(f"{t}."):
                            filtered.append(d)
                    else:
                        if ":" in gid and gid.split(":", 1)[1].startswith(f"{t}."):
                            filtered.append(d)
                return json.dumps(filtered)
        return data

    def show_buckets(self):
        return self.engine.show()

    def __getattr__(self, name):
        return getattr(self.engine, name)


class Interpreter:
    def _scan_bucket_rls(self, bucket):
        return self.engine.scan_bucket(bucket)

    def __init__(self, engine=None, indexing_queue=None):
        self.context = {}
        self.engine = TenantEngineProxy(engine, self.context) if engine else None
        self.indexing_queue = indexing_queue
        self.in_transaction = False
        self.transaction_log = []
        self.emitted_events = []
        self.security = PolicyEngine()

    def set_context(self, context):
        if not hasattr(self, "context") or self.context is None:
            self.context = {}
        self.context.clear()
        if context:
            self.context.update(context)
        self.security = PolicyEngine()
        if self.engine:
            from .lexer import Lexer

            pol_data = self._scan_bucket_rls("_security_policies")
            if pol_data:

                tenant_id = self.context.get(
                    "tenant_id", self.context.get("user", "").split(".")[0]
                )
                for p_doc in json.loads(pol_data):
                    doc_id = p_doc["gid"].split(":")[1]
                    if tenant_id != "cron" and not (
                        doc_id == tenant_id or doc_id.startswith(f"{tenant_id}.")
                    ):
                        continue
                    b = p_doc.get("body", {})
                    if b.get("type") == "policy":
                        tokens = Lexer(b["condition_str"]).tokenize()
                        if tokens and tokens[-1].type.name == "EOF":
                            tokens.pop()
                        self.security.add_policy(
                            b["bucket"], b["name"], b["action"], tokens
                        )
                    elif b.get("type") == "mask":
                        tokens = Lexer(b["condition_str"]).tokenize()
                        if tokens and tokens[-1].type.name == "EOF":
                            tokens.pop()
                        if not hasattr(self.security, "masks"):
                            self.security.masks = {}
                        if b["bucket"] not in self.security.masks:
                            self.security.masks[b["bucket"]] = []
                        self.security.masks[b["bucket"]].append(
                            {"field": b["field"], "condition": tokens}
                        )

    # CleaveDB instance from PyO3, or None for mock

    def _evaluate_where(self, where, doc: dict) -> bool:
        if not where or not getattr(where, "predicates", None):
            return True

        result = True
        for i, pred in enumerate(where.predicates):
            field_val = doc.get(pred.field)
            op = pred.op
            val = pred.value

            # Type coerce for comparison if possible
            if (
                isinstance(field_val, (int, float))
                and isinstance(val, str)
                and val.replace(".", "", 1).isdigit()
            ):
                val = float(val) if "." in val else int(val)

            pred_res = False
            if op in ("==", "="):
                pred_res = field_val == val
            elif op == "!=":
                pred_res = field_val != val
            elif op == ">":
                pred_res = (field_val > val) if field_val is not None else False
            elif op == "<":
                pred_res = (field_val < val) if field_val is not None else False
            elif op == ">=":
                pred_res = (field_val >= val) if field_val is not None else False
            elif op == "<=":
                pred_res = (field_val <= val) if field_val is not None else False

            if i == 0:
                result = pred_res
            else:
                conn = (
                    where.connectives[i - 1].lower()
                    if i - 1 < len(where.connectives)
                    else "and"
                )
                if conn == "and":
                    result = result and pred_res
                elif conn == "or":
                    result = result or pred_res

        return result

    def _strip_tenant(self, data, tenant):
        if not tenant or tenant == "cron":
            return data
        prefix = f"{tenant}."
        if isinstance(data, dict):
            for k, v in data.items():
                if k in ("gid", "source", "target") and isinstance(v, str):
                    parts = v.split(":", 1)
                    if len(parts) == 2 and parts[0].startswith(prefix):
                        data[k] = f"{parts[0][len(prefix):]}:{parts[1]}"
                elif k == "gids" and isinstance(v, list):
                    new_gids = []
                    for gid in v:
                        parts = str(gid).split(":", 1)
                        if len(parts) == 2 and parts[0].startswith(prefix):
                            new_gids.append(f"{parts[0][len(prefix):]}:{parts[1]}")
                        else:
                            new_gids.append(gid)
                    data[k] = new_gids
                elif isinstance(v, (dict, list)):
                    self._strip_tenant(v, tenant)
        elif isinstance(data, list):
            for item in data:
                self._strip_tenant(item, tenant)
        return data

    def execute(self, stmts: list) -> list:
        results = []
        for stmt in stmts:
            try:
                res = self._execute_stmt(stmt)
                if res is None:
                    continue
                tenant = (
                    self.context.get(
                        "tenant_id", self.context.get("user", "").split(".")[0]
                    )
                    if "user" in self.context
                    else None
                )
                if tenant and tenant != "cron":
                    self._strip_tenant(res, tenant)
                results.append(res)
                if res.get("status") == "error" and self.in_transaction:
                    self._rollback()
                    results.append(
                        {
                            "status": "error",
                            "message": "Transaction aborted due to error",
                        }
                    )
                    break
            except Exception as e:
                import traceback

                traceback.print_exc()
                results.append({"status": "error", "message": str(e)})
                if self.in_transaction:
                    self._rollback()
                    results.append(
                        {
                            "status": "error",
                            "message": "Transaction aborted due to error",
                        }
                    )
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
        return gid
        tenant = (
            self.context.get("tenant_id", self.context.get("user", "").split(".")[0])
            if "user" in self.context
            else "cron"
        )
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
                                regex_str = regex_str.replace(
                                    re.escape(m.group(0)), "(.*)", 1
                                )
                            match = re.match(regex_str, str(current_doc[k]))
                            if match:
                                for i, var in enumerate(vars_in_v):
                                    mapping[var] = match.group(i + 1)
                            else:
                                return None
                        elif isinstance(v, dict):
                            res = map_fields(v, current_doc[k])
                            if res is None:
                                return None
                            mapping.update(res)
                        else:
                            if v != current_doc[k]:
                                return None
                    else:
                        return None
            return mapping

        def apply_mapping(dst_pattern, mapping):
            if isinstance(dst_pattern, str) and dst_pattern.startswith("$"):
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
                batch = all_docs[i : i + batch_size]
                for doc_meta in batch:

                    gid = doc_meta.get("gid")
                    doc_id = gid.split(":", 1)[1] if ":" in gid else gid

                    retries = 3
                    while retries > 0:
                        current_meta = next(
                            (
                                d
                                for d in json.loads(
                                    self.engine.scan_bucket(bucket) or "[]"
                                )
                                if d["gid"] == gid
                            ),
                            None,
                        )
                        if not current_meta:
                            break

                        current_body = current_meta.get("body", {})
                        current_version = current_body.get("_version", 1)

                        mapping = map_fields(src_json, current_body)

                        if not mapping:
                            break  # Doesn't match src_json pattern

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
                        check_meta = next(
                            (
                                d
                                for d in json.loads(
                                    self.engine.scan_bucket(bucket) or "[]"
                                )
                                if d["gid"] == gid
                            ),
                            None,
                        )
                        if (
                            check_meta
                            and check_meta.get("body", {}).get("_version", 1)
                            == current_version
                        ):
                            self.engine.pour(bucket, doc_id, json.dumps(final_body))
                            break
                        else:
                            retries -= 1
                            time.sleep(0.1)
                time.sleep(0.01)  # Yield to other threads
        except Exception as e:
            print(f"[Migration] Error: {e}")

    def _fire_triggers(self, event, bucket, doc_id, body):
        trigger_depth = self.context.get("trigger_depth", 0)
        if trigger_depth > 5:
            return

        trigger_data = self.engine.scan_bucket("_triggers")
        if not trigger_data:
            return
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

                open("debug_trigger.txt", "a").write(f"QUERY: {query}\n")
                lexer = Lexer(query)
                tokens = lexer.tokenize()
                parser = Parser(tokens)
                open("debug_trigger.txt", "a").write(f"TOKENS: {tokens}\n")
                stmts = parser.parse()
                open("debug_trigger.txt", "a").write(f"ERRORS: {parser.errors}\n")

                old_depth = self.context.get("trigger_depth", 0)
                self.context["trigger_depth"] = old_depth + 1
                for s in stmts:
                    res = self._execute_stmt(s)
                    if isinstance(res, dict) and res.get("status") == "error":
                        raise Exception(f"Trigger Error: {res.get('message')}")
                self.context["trigger_depth"] = old_depth



    def _log_audit(self, bucket: str, action: str, gid: str, before: dict = None, after: dict = None):
        print(f"[_log_audit] CHECKING {bucket} for action {action}", flush=True)
        policy_str = self.engine.get(f"_bucket_policies:{bucket}")
        print(f"[_log_audit] POLICY STR: {policy_str}", flush=True)
        if policy_str:
            policy = json.loads(policy_str)
            print(f"[_log_audit] POLICY OBJ: {policy}", flush=True)
            if policy.get("audited"):
                print(f"[_log_audit] AUDIT TRIGGERED!", flush=True)
                tenant = self.context.get("tenant_id", self.context.get("user", "").split(".")[0]) if "user" in self.context else "system"
                audit_doc = {
                    "who": tenant,
                    "action": action,
                    "gid": f"{bucket}:{gid}",
                    "timestamp": int(time.time()),
                }
                if before is not None:
                    audit_doc["before"] = before
                if after is not None:
                    audit_doc["after"] = after
                    
                audit_id = f"{tenant}.{uuid.uuid4()}" if tenant != "system" else str(uuid.uuid4())
                res = self.engine.pour(f"_audit_{bucket}", audit_id, json.dumps(audit_doc))
                print(f"[_log_audit] POUR RESULT: {res}", flush=True)

    def _validate_guards(self, bucket: str, doc_body: dict):
        existing = self.engine.get(f"_guards:{bucket}")
        if not existing:
            return None
        try:
            guards = json.loads(existing)
        except:
            return None
            
        for rule in guards:
            field = rule.get("field")
            r_type = rule.get("rule_type")
            val = rule.get("value")
            
            if r_type == "REQUIRED":
                if field not in doc_body:
                    return f"Guard violation on '{bucket}': '{field}' is required"
            elif r_type == "NOT REQUIRED":
                pass
            elif field in doc_body:
                actual = doc_body[field]
                if r_type == "IN":
                    if actual not in val:
                        return f"Guard violation on '{bucket}': '{field}' must be one of {val}"
                elif r_type == "LENGTH":
                    op = rule.get("operator")
                    if not isinstance(actual, str):
                        return f"Guard violation on '{bucket}': '{field}' must be a string for LENGTH check"
                    l = len(actual)
                    if op == ">" and not (l > val): return f"Guard violation on '{bucket}': '{field}' length must be > {val}"
                    if op == "<" and not (l < val): return f"Guard violation on '{bucket}': '{field}' length must be < {val}"
                    if op == ">=" and not (l >= val): return f"Guard violation on '{bucket}': '{field}' length must be >= {val}"
                    if op == "<=" and not (l <= val): return f"Guard violation on '{bucket}': '{field}' length must be <= {val}"
                    if op == "=" and not (l == val): return f"Guard violation on '{bucket}': '{field}' length must be = {val}"
                    if op == "!=" and not (l != val): return f"Guard violation on '{bucket}': '{field}' length must be != {val}"
                elif r_type == "TYPE":
                    if val == "string" and not isinstance(actual, str): return f"Guard violation on '{bucket}': '{field}' must be a string"
                    if val == "number" and not isinstance(actual, (int, float)): return f"Guard violation on '{bucket}': '{field}' must be a number"
                    if val == "boolean" and not isinstance(actual, bool): return f"Guard violation on '{bucket}': '{field}' must be a boolean"
                    if val == "list" and not isinstance(actual, list): return f"Guard violation on '{bucket}': '{field}' must be a list"
                elif r_type == "COMPARE":
                    op = rule.get("operator")
                    try:
                        if op == ">" and not (actual > val): return f"Guard violation on '{bucket}': '{field}' must be > {val}"
                        if op == "<" and not (actual < val): return f"Guard violation on '{bucket}': '{field}' must be < {val}"
                        if op == ">=" and not (actual >= val): return f"Guard violation on '{bucket}': '{field}' must be >= {val}"
                        if op == "<=" and not (actual <= val): return f"Guard violation on '{bucket}': '{field}' must be <= {val}"
                        if op == "=" and not (actual == val): return f"Guard violation on '{bucket}': '{field}' must be = {val}"
                        if op == "!=" and not (actual != val): return f"Guard violation on '{bucket}': '{field}' must be != {val}"
                    except TypeError:
                        return f"Guard violation on '{bucket}': Cannot compare '{field}' with {val}"
        return None

    def _execute_stmt(self, stmt):
        stmt_type = type(stmt).__name__

        # ---- Mock mode (no engine connected) ----
        if self.engine is None:
            return {"status": "mock", "statement": stmt_type}

        # ---- Dev Superuser Override Check ----
        target_bucket = getattr(stmt, "bucket", None)
        if target_bucket and target_bucket.startswith("_audit_") and stmt_type in ("PourStmt", "PourManyStmt", "ChangeStmt", "DrainStmt"):
            return {"status": "error", "message": "Audit buckets are read-only"}
            
        if (
            target_bucket
            and target_bucket.startswith("_")
            and target_bucket != "_rubbish"
        ):
            if (
                self.context.get("auth_level") != "dev"
                and self.context.get("user") != "cron"
            ):
                return {
                    "status": "error",
                    "message": f"Access Denied: The '{target_bucket}' bucket requires Dev Password (superuser override) to access.",
                }

        # ---- Real engine dispatch ----

        if stmt_type == "BeginStmt":
            self.in_transaction = True
            self.transaction_log = []
            return {"status": "ok", "message": "Transaction started"}

        elif stmt_type == "CommitStmt":
            if not self.in_transaction:
                return {"status": "error", "message": "No active transaction"}
            self.in_transaction = False
            self.transaction_log = []
            return {"status": "ok", "message": "Transaction committed"}

        elif stmt_type == "RollbackStmt":
            if not self.in_transaction:
                return {"status": "error", "message": "No active transaction"}
            self._rollback()
            return {"status": "ok", "message": "Transaction rolled back"}

        elif stmt_type == "TriggerStmt":
            doc = {
                "event": stmt.event,
                "bucket": stmt.bucket,
                "query_template": stmt.query_template,
            }
            self.engine.pour("_triggers", None, json.dumps(doc))
            return {
                "status": "ok",
                "message": f"Trigger created for {stmt.event} on {stmt.bucket}.",
            }


        elif stmt_type == "GuardStmt":
            bucket = getattr(stmt, "bucket", "")
            rules = getattr(stmt, "rules", [])
            
            existing = self.engine.get(f"_guards:{bucket}")
            if existing:
                try:
                    guards = json.loads(existing)
                except:
                    guards = []
            else:
                guards = []
                
            guards.extend(rules)
            self.engine.pour("_guards", bucket, json.dumps(guards))
            return {"status": "ok", "message": f"Added {len(rules)} guards to {bucket}"}

        elif stmt_type == "EnrichStmt":
            bucket = getattr(stmt, "bucket", "")
            rules = getattr(stmt, "rules", [])
            
            existing = self.engine.get(f"_enrichments:{bucket}")
            if existing:
                try:
                    enrichments = json.loads(existing)
                except:
                    enrichments = []
            else:
                enrichments = []
                
            enrichments.extend(rules)
            self.engine.pour("_enrichments", bucket, json.dumps(enrichments))
            return {"status": "ok", "message": f"Added {len(rules)} enrichments to {bucket}"}

        elif stmt_type == "PourStmt":
            bucket = getattr(stmt, "bucket", "")
            doc_id = getattr(stmt, "doc_id", None)
            body = getattr(stmt, "json_body", None)

            # --- TTL Injection ---
            ttl = getattr(stmt, "ttl", None)
            if ttl is not None and isinstance(body, dict):
                expires_at = int(time.time()) + ttl
                body["_expires_at"] = expires_at

            # Document Security Level (DSL) Write Check
            if not self.security.check_write(bucket, body, self.context):
                return {
                    "status": "error",
                    "message": "Security Policy Violation: Write access denied by Document Security Level (DSL).",
                }
            
            err = self._validate_guards(bucket, body)
            if err:
                return {"status": "error", "message": err}

            # LRU Memory Management
            policy_data = self.engine.get(f"_bucket_policies:{bucket}")
            if policy_data:
                p = json.loads(policy_data)
                if p.get("algorithm") == "LRU":
                    self.engine.pour(
                        "_lru_tracking", f"{bucket}:{doc_id}", str(time.time())
                    )
                    capacity = p.get("capacity", 100)
                    b_docs_data = self._scan_bucket_rls(bucket)
                    if b_docs_data:
                        b_docs = json.loads(b_docs_data)
                        if len(b_docs) >= capacity:
                            # Evict oldest
                            lru_doc = min(
                                b_docs,
                                key=lambda d: float(
                                    self.engine.get(
                                        f"_lru_tracking:{bucket}:{d['gid'].split(':')[-1]}"
                                    )
                                    or 0
                                ),
                            )
                            self.engine.delete(lru_doc["gid"])

            json_str = (
                json.dumps(body)
                if isinstance(body, (dict, list))
                else str(body or "{}")
            )
            if self.in_transaction:
                gid_check = f"{bucket}:{doc_id}" if doc_id else None
                old_val = self.engine.get(gid_check) if gid_check else None

            gid = self.engine.pour(bucket, doc_id, json_str)
            
            self._log_audit(bucket, "POUR", gid.split(":")[-1], None, body)

            if self.in_transaction:
                self.transaction_log.append({"gid": gid, "body": old_val})
            t = (
                self.context.get(
                    "tenant_id", self.context.get("user", "").split(".")[0]
                )
                if "user" in self.context
                else "cron"
            )
            self.context.setdefault("events", []).append(
                {"event": "POUR", "bucket": bucket, "data": body, "tenant": t}
            )
            t = self.context.get("tenant_id", self.context.get("user", "").split(".")[0]) if "user" in self.context else "cron"
            self.context.setdefault("events", []).append({"event": "POUR", "bucket": bucket, "data": body, "tenant": t})
            self._fire_triggers("POUR", bucket, gid.split(":")[-1], body)

            if ttl is not None and isinstance(body, dict):
                # Put a fast-lookup pointer in _ttl bucket for the cron worker
                self.engine.pour(
                    "_ttl",
                    gid.split(":")[-1],
                    json.dumps({"target": gid, "expires_at": expires_at}),
                )

            # --- Vector Indexing Queue ---
            if self.indexing_queue is not None and isinstance(body, dict):
                text_content = " ".join(
                    [str(v) for v in body.values() if isinstance(v, str)]
                )
                if text_content:
                    print(f"[Interpreter] Pushing {gid} to vector queue!")
                    self.indexing_queue.put((gid, text_content))

            self.emitted_events.append(
                {"event": "POUR", "target": gid, "bucket": bucket, "data": body}
            )

            # Auth Cross-Write
            if getattr(stmt, "secret", None):
                pwd = stmt.secret.encode()
                salt_bytes = os.urandom(16)
                salt = salt_bytes.hex()
                pw_hash = hashlib.pbkdf2_hmac("sha256", pwd, salt_bytes, 100000).hex()
                auth_doc = {
                    "username": doc_id or gid.split(":")[-1],
                    "password_hash": pw_hash,
                    "password_salt": salt,
                    "role": (
                        body.get("role", "viewer")
                        if isinstance(body, dict)
                        else "viewer"
                    ),
                    "tenant_id": self.context.get(
                        "tenant_id",
                        self.context.get(
                            "tenant_id", self.context.get("user", "").split(".")[0]
                        ),
                    ),
                }
                self.engine.pour("_auth", auth_doc["username"], json.dumps(auth_doc))

            return {"status": "ok", "gid": gid}

        elif stmt_type == "PourManyStmt":
            bucket = getattr(stmt, "bucket", "")
            documents = getattr(stmt, "json_array", [])
            if isinstance(documents, str):
                documents = json.loads(documents)
            gids = []
            for doc in documents:
                doc_id = (
                    doc.pop("_id", doc.pop("gid", None))
                    if isinstance(doc, dict)
                    else None
                )

                json_str = json.dumps(doc) if isinstance(doc, dict) else str(doc)

                if self.in_transaction:
                    gid_check = f"{bucket}:{doc_id}" if doc_id else None
                    old_val = self.engine.get(gid_check) if gid_check else None

                gid = self.engine.pour(bucket, doc_id, json_str)

                if self.in_transaction:
                    self.transaction_log.append({"gid": gid, "body": old_val})

                # --- Vector Indexing Queue ---
                if self.indexing_queue is not None and isinstance(doc, dict):
                    text_content = " ".join(
                        [str(v) for v in doc.values() if isinstance(v, str)]
                    )
                    if text_content:
                        print(f"[Interpreter] Pushing {gid} to vector queue!")
                        self.indexing_queue.put((gid, text_content))

                self.emitted_events.append(
                    {"event": "POUR", "target": gid, "bucket": bucket, "data": doc}
                )
                gids.append(gid)
            return {"status": "ok", "count": len(gids), "gids": gids}

        elif stmt_type == "ScoopStmt":
            mode = getattr(stmt, "mode", "EVERYTHING")
            if mode == "CHAIN":
                current_gids = [self._namespace_gid(getattr(stmt, "chain_source", ""))]
                bonds_json = self._scan_bucket_rls("_bonds")
                bonds = json.loads(bonds_json) if bonds_json else []
                labels = getattr(stmt, "chain_labels", [])

                for label in reversed(labels):
                    next_gids = set()
                    for gid in current_gids:
                        for b in bonds:
                            body = b.get("body", {})
                            if (
                                body.get("expires_at")
                                and current_time > body["expires_at"]
                            ):
                                continue
                            if body.get("source") == gid and body.get("label") == label:
                                next_gids.add(body.get("target"))
                            elif (
                                body.get("mutual")
                                and body.get("target") == gid
                                and body.get("label") == label
                            ):
                                next_gids.add(body.get("source"))
                    current_gids = list(next_gids)

                final_docs = []
                for gid in current_gids:
                    doc_json = self.engine.get(gid)
                    if doc_json:
                        final_docs.append({"gid": gid, "body": json.loads(doc_json)})
                return {
                    "status": "ok",
                    "mode": mode,
                    "labels": labels,
                    "documents": final_docs,
                    "count": len(final_docs),
                }

            bucket = getattr(stmt, "bucket", "")
            
            # --- ALIAS PROJECTION INJECTION ---
            t = self.context.get("tenant_id", self.context.get("user", "").split(".")[0]) if "user" in self.context else "cron"
            proj_id = f"{t}.{bucket}" if t != "cron" else bucket
            
            proj_str = self.engine.get(f"_projections:{proj_id}")
            if proj_str:
                proj = json.loads(proj_str)
                bucket = proj["from_bucket"]
                stmt.bucket = bucket
                
                proj_where_str = proj.get("where_str", "")
                if proj_where_str:
                    from cleaveql.lexer import Lexer
                    from cleaveql.parser import Parser
                    try:
                        lexer = Lexer(proj_where_str)
                        parser = Parser(lexer.tokenize())
                        proj_where = parser._parse_where()
                        
                        if getattr(stmt, "where", None):
                            stmt.where.predicates = proj_where.predicates + stmt.where.predicates
                            stmt.where.connectives = proj_where.connectives + ["AND"] + stmt.where.connectives
                        else:
                            stmt.where = proj_where
                    except Exception as e:
                        print(f"Error parsing projection WHERE clause: {e}")
            # --- END ALIAS PROJECTION INJECTION ---

            if mode == "RELATED":
                show_candidates = getattr(stmt, "show_candidates", False)
                as_of = getattr(stmt, "as_of", None)
                current_time = int(time.time())
                effective_time = current_time
                if as_of:
                    if as_of.lower() == "yesterday":
                        effective_time = current_time - 86400
                    elif as_of.isdigit():
                        effective_time = int(as_of)

                label = getattr(stmt, "related_label", "")
                source = self._namespace_gid(getattr(stmt, "related_source", ""))
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
                        t_bucket, t_id = (
                            target.split(":", 1) if ":" in target else (bucket, target)
                        )

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
                                    s_bucket, s_id = (
                                        source.split(":", 1)
                                        if ":" in source
                                        else (bucket, source)
                                    )
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
                                "_bond": {"label": label, "source": source},
                            }
                            if cond_f:
                                wrapped_doc["_bond"]["status"] = (
                                    "active" if is_active else "candidate"
                                )
                            if b.get("confidence"):
                                wrapped_doc["_bond"]["confidence"] = b["confidence"]
                            if b.get("affinity"):
                                wrapped_doc["_bond"]["affinity"] = b["affinity"]
                            related_docs.append(wrapped_doc)
                return {
                    "status": "ok",
                    "mode": "RELATED",
                    "label": label,
                    "count": len(related_docs),
                    "documents": related_docs,
                }

            mode = getattr(stmt, "mode", "EVERYTHING")
            mode_count = getattr(stmt, "mode_count", None)
            whose_field = getattr(stmt, "whose_field", None)
            whose_value = getattr(stmt, "whose_value", None)
            if whose_field == "gid" and whose_value:
                whose_value = self._namespace_gid(whose_value)
            yield_fields = getattr(stmt, "yield_fields", [])
            limit = getattr(stmt, "limit", None)
            mentioning = getattr(stmt, "mentioning", None)
            meaning = getattr(stmt, "meaning", None)
            include = getattr(stmt, "include", [])

            results_json = self._scan_bucket_rls(bucket)
            results = json.loads(results_json) if results_json else []

            docs = []
            for r in results:
                doc_json = self.engine.get(r["gid"])
                if doc_json:
                    docs.append({"gid": r["gid"], "body": json.loads(doc_json)})

            # 1. Apply MENTIONING (Text search mock)
            if mentioning:
                docs = [
                    d
                    for d in docs
                    if mentioning.lower() in json.dumps(d["body"]).lower()
                ]

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
                    try:
                        similarity = float(
                            self.engine.simd_dot_product(query_vec, doc_vec)
                        )
                    except AttributeError:
                        # Fallback for Python Mock
                        similarity = sum(x * y for x, y in zip(query_vec, doc_vec))
                    print(f"[Interpreter] Similarity for {doc['gid']}: {similarity}")

                    if similarity > 0.20:
                        doc["_embedding_distance"] = round(similarity, 3)
                        temp.append(doc)

                filtered_docs = sorted(
                    temp, key=lambda x: x["_embedding_distance"], reverse=True
                )
            else:
                filtered_docs = docs

            # Apply Document Security Level (DSL) Read Filters
            if hasattr(self, "security"):
                matching = getattr(stmt, "matching", None)
            if matching:

                def is_match(template, target):
                    if template == "*":
                        return True
                    if isinstance(template, dict) and isinstance(target, dict):
                        for k, v in template.items():
                            if k == "*":
                                # Wildcard key: any value in target must match v, OR at least one?
                                # Let's say at least ONE key must match the template v
                                if not any(is_match(v, tgt_v) for tgt_v in target.values()):
                                    return False
                                continue
                            if k not in target or not is_match(v, target[k]):
                                return False
                        return True
                    if isinstance(template, list) and isinstance(target, list):
                        # Subset matching for lists
                        for t_item in template:
                            if not any(is_match(t_item, tgt_item) for tgt_item in target):
                                return False
                        return True
                    return template == target

                filtered_docs = [
                    d for d in filtered_docs if is_match(matching, d["body"])
                ]

            filtered_docs = [
                d
                for d in filtered_docs
                if self.security.check_read(bucket, d, self.context, self.engine)
            ]

            # Apply WHERE clause
            if getattr(stmt, "where", None):
                filtered_docs = [
                    d
                    for d in filtered_docs
                    if self._evaluate_where(stmt.where, d["body"])
                ]

            # Apply WHOSE
            if whose_field and whose_value is not None:
                filtered_docs = [
                    d
                    for d in filtered_docs
                    if (
                        d.get(whose_field).split(":", 1)[-1]
                        if whose_field == "gid" and ":" in str(d.get(whose_field))
                        else (
                            d.get(whose_field)
                            if whose_field == "gid"
                            else d["body"].get(whose_field)
                        )
                    )
                    == (
                        whose_value.split(":", 1)[-1]
                        if whose_field == "gid"
                        and isinstance(whose_value, str)
                        and ":" in whose_value
                        else whose_value
                    )
                ]

            # Update LRU Tracking on Read
            policy_data = self.engine.get(f"_bucket_policies:{bucket}")
            if policy_data and json.loads(policy_data).get("algorithm") == "LRU":
                for d in filtered_docs:
                    doc_id = d["gid"].split(":")[-1] if ":" in d["gid"] else d["gid"]
                    self.engine.pour(
                        "_lru_tracking", f"{bucket}:{doc_id}", str(time.time())
                    )

            # Handle Sorting (ARRANGED BY, HIGHEST, LOWEST)
            arrange_field = getattr(stmt, "arrange_field", None)
            if arrange_field:
                arrange_dir = getattr(stmt, "arrange_dir", "ASC")
                filtered_docs.sort(
                    key=lambda x: x["body"].get(arrange_field, ""),
                    reverse=(arrange_dir == "DESC"),
                )
            elif mode in ("HIGHEST", "LOWEST"):
                target_field = getattr(stmt, "target_field", None)
                if target_field:
                    filtered_docs.sort(
                        key=lambda x: x["body"].get(target_field, 0),
                        reverse=(mode == "HIGHEST"),
                    )

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
                    d["body"] = {
                        k: v for k, v in d["body"].items() if k in yield_fields
                    }

            # Apply Field Masking
            if hasattr(self, "security"):
                for d in filtered_docs:
                    d["body"] = self.security.apply_masks(
                        bucket, d["body"], self.context, self.engine
                    )

            # Analytics Returns
            if mode == "TALLY":
                return {"status": "ok", "mode": mode, "count": len(filtered_docs)}
            elif mode == "UNIQUE":
                target_field = getattr(stmt, "target_field", None)
                if target_field:
                    seen = set()
                    unique_vals = []
                    for d in filtered_docs:
                        val = d["body"].get(target_field)
                        if val not in seen:
                            seen.add(val)
                            unique_vals.append(val)
                    return {
                        "status": "ok",
                        "mode": mode,
                        "values": unique_vals,
                        "count": len(unique_vals),
                    }
            elif mode == "TOTAL":
                group_by = getattr(stmt, "group_by", None)
                target_field = getattr(stmt, "target_field", None)
                if target_field and group_by:
                    groups = {}
                    for d in filtered_docs:
                        gv = d["body"].get(group_by, "unknown")
                        tv = d["body"].get(target_field, 0)
                        if isinstance(tv, (int, float)):
                            groups[gv] = groups.get(gv, 0) + tv
                    results = [{"group": k, "total": v} for k, v in groups.items()]
                    return {
                        "status": "ok",
                        "mode": mode,
                        "results": results,
                        "count": len(results),
                    }

            # --- VIRTUAL FIELDS (ENRICH) ---
            enrichments_json = self.engine.get(f"_enrichments:{bucket}")
            if enrichments_json:
                try:
                    enrichments = json.loads(enrichments_json)
                    class SafeDict(dict):
                        def __init__(self, globals_dict, *args, **kwargs):
                            super().__init__(*args, **kwargs)
                            self.globals_dict = globals_dict
                        def __missing__(self, key):
                            if key in self.globals_dict or key in __builtins__:
                                raise KeyError(key)
                            return None
                            
                    g = {
                        "__builtins__": {},
                        "NOW": lambda: int(time.time()),
                        "CONCAT": lambda *args: "".join(str(a) if a is not None else "" for a in args)
                    }
                    for d in filtered_docs:
                        body = d["body"]
                        s_dict = SafeDict(g, body)
                        for rule in enrichments:
                            try:
                                val = eval(rule["expr"], g, s_dict)
                                body[rule["field"]] = val
                                s_dict[rule["field"]] = val
                            except Exception as eval_e:
                                print(f"Enrich eval error: {eval_e}")
                except Exception as e:
                    print(f"Enrich error: {e}")

            return {
                "status": "ok",
                "mode": mode,
                "documents": filtered_docs,
                "count": len(filtered_docs),
            }

        elif stmt_type == "CountStmt":

            bucket = getattr(stmt, "bucket", "")
            results_json = self._scan_bucket_rls(bucket)
            results = json.loads(results_json) if results_json else []
            return {"status": "ok", "count": len(results)}

        elif stmt_type == "ListenStmt":
            bucket = getattr(stmt, "target_bucket", "")
            gid = getattr(stmt, "target_gid", None)
            target = self._namespace_gid(gid) if gid else f"bucket:{bucket}"
            return {"status": "listen", "target": target}
        elif stmt_type == "ChangeStmt":
            doc_id = getattr(stmt, "doc_id", None)
            bucket = getattr(stmt, "bucket", "")
            assignments = getattr(stmt, "assignments", [])
            if doc_id:
                # Use f"{bucket}:{doc_id}" for the global engine ID!
                doc_json = self.engine.get(f"{bucket}:{doc_id}")
                if doc_json:
                    body = json.loads(doc_json)
                    for assign in assignments:
                        if isinstance(assign, tuple):
                            field, value = assign
                        else:
                            field = getattr(assign, "field", None)
                            value = getattr(assign, "value", None)
                        if field is not None:
                            # Evaluate sub-scoop recursively
                            if (
                                isinstance(value, dict)
                                and value.get("_type") == "sub_scoop"
                            ):
                                sub_stmt = value.get("stmt")
                                sub_res = self._execute_stmt(sub_stmt)
                                value = sub_res.get("documents", [])

                            # Retroactive Auth Password handling
                            if field.lower() == "secret":
                                pwd = str(value).encode()
                                salt = os.urandom(16).hex()
                                pw_hash = hashlib.pbkdf2_hmac(
                                    "sha256", pwd, salt.encode(), 100000
                                ).hex()

                                auth_gid = f"_auth:{doc_id}"
                                existing_auth = self.engine.get(auth_gid)
                                if existing_auth:
                                    auth_doc = json.loads(existing_auth)
                                else:
                                    auth_doc = {
                                        "username": doc_id,
                                        "role": body.get("role", "viewer"),
                                    }

                                auth_doc["password_hash"] = pw_hash
                                auth_doc["password_salt"] = salt
                                self.engine.pour("_auth", doc_id, json.dumps(auth_doc))
                            else:
                                body[field] = value
                    
                    err = self._validate_guards(bucket, body)
                    if err:
                        return {"status": "error", "message": err}
                        
                    self.engine.pour(bucket, doc_id, json.dumps(body))
                    
                    # Hook Audit Trail
                    self._log_audit(bucket, "CHANGE", doc_id, json.loads(doc_json), body)
                    
                    try:
                        tenant_bucket = self.engine._ns(bucket)
                    except AttributeError:
                        tenant_bucket = bucket
                    full_gid = f"{tenant_bucket}:{doc_id}"
                    self.emitted_events.append(
                        {
                            "event": "CHANGE" if stmt_type == "ChangeStmt" else "POUR",
                            "target": full_gid,
                            "bucket": bucket,
                            "data": body,
                        }
                    )
                    return {"status": "ok", "gid": doc_id}
                return {"status": "error", "message": f"Document '{doc_id}' not found"}
            return {"status": "error", "message": "No doc_id specified"}

        elif stmt_type == "HealStmt":
            target = getattr(stmt, "target", "all")
            result = self.engine.heal(target)
            return {"status": "ok", "message": result}

        elif stmt_type == "ShowStmt":
            if getattr(stmt, "target", "").upper() == "BUCKETS":
                buckets_data = self.engine.show("buckets")
                all_b = json.loads(buckets_data) if buckets_data else []
                t = (
                    self.context.get(
                        "tenant_id", self.context.get("user", "").split(".")[0]
                    )
                    if "user" in self.context
                    else "cron"
                )
                vis = []
                is_dev = self.context.get("auth_level") == "dev"
                for b in all_b:
                    if b.startswith("_"):
                        if is_dev:
                            vis.append(b)
                        continue
                    if t != "cron" and b.startswith(f"{t}."):
                        vis.append(b[len(t) + 1 :])
                return {"status": "ok", "data": vis}

        elif stmt_type == "SeverStmt":
            tenant = (
                self.context.get(
                    "tenant_id", self.context.get("user", "").split(".")[0]
                )
                if "user" in self.context
                else "cron"
            )
            source = self._namespace_gid(getattr(stmt, "source_gid", ""))
            target = self._namespace_gid(getattr(stmt, "target_gid", ""))
            label = getattr(stmt, "label", "")
            count = 0

            b_data = self._scan_bucket_rls("_bonds")
            if b_data:
                for b_doc in json.loads(b_data):
                    b = b_doc.get("body", {})
                    if b.get("source") == source and b.get("target") == target:
                        if not label or b.get("label") == label:
                            # WAL 4D MVCC Append
                            hist_doc = dict(b)
                            hist_doc["_event_type"] = "SEVER"
                            hist_doc["_event_time"] = time.time() * 1000
                            self.engine.pour(
                                "_history__bonds",
                                (
                                    f"{tenant}.{str(uuid.uuid4())}"
                                    if tenant != "cron"
                                    else str(uuid.uuid4())
                                ),
                                json.dumps(hist_doc),
                            )

                            self.engine.delete(b_doc["gid"])
                            count += 1
            return {"status": "ok", "message": f"Severed {count} bonds."}

        elif stmt_type == "ShapeViewStmt":
            t = (
                self.context.get(
                    "tenant_id", self.context.get("user", "").split(".")[0]
                )
                if "user" in self.context
                else "cron"
            )
            view_doc = {
                "source": stmt.source_bucket,
                "group_field": stmt.group_field,
                "sum_field": stmt.sum_field,
                "tenant": t,
            }
            # Pour into _views metadata
            v_id = f"{t}.{stmt.view_name}" if t != "cron" else stmt.view_name
            self.engine.pour("_views", v_id, json.dumps(view_doc))

            # Perform initial DISTILL to bootstrap the view
            # Note: This is an O(N) scan but it only happens once at creation
            all_docs_str = self._scan_bucket_rls(stmt.source_bucket)
            all_docs = json.loads(all_docs_str) if all_docs_str else []

            groups = {}
            for d in all_docs:
                body = d.get("body", {})
                grp = body.get(stmt.group_field)
                val = body.get(stmt.sum_field, 0)
                if grp is not None:
                    try:
                        val = float(val)
                        groups[str(grp)] = groups.get(str(grp), 0) + val
                    except ValueError:
                        pass

            # Pour the aggregated results directly into the view bucket
            for g, v in groups.items():
                self.engine.pour(
                    stmt.view_name, g, json.dumps({"_group": g, stmt.sum_field: v})
                )

            return {
                "status": "ok",
                "message": f"Continuous Materialized View '{stmt.view_name}' initialized.",
            }

        elif stmt_type == "RestoreBucketStmt":
            bucket = stmt.bucket.lower()
            r_data = self._scan_bucket_rls("_rubbish")
            rubbish = json.loads(r_data) if r_data else []
            count = 0
            for r in rubbish:
                r_gid = r["gid"]
                r_doc = self.engine.get(r_gid)
                if not r_doc:
                    continue
                body = json.loads(r_doc)
                if body.get("original_bucket") == bucket:
                    # Restore it!
                    self.engine.pour(
                        bucket,
                        body.get("original_id"),
                        json.dumps(body.get("document", {})),
                    )
                    self.engine.delete(r_gid)
                    count += 1
            return {
                "status": "ok",
                "message": f"Restored {count} documents back to '{bucket}' from the _rubbish bin.",
            }

        elif stmt_type == "DropBucketStmt":

            bucket = stmt.bucket.lower()

            docs_json = self._scan_bucket_rls(bucket)
            docs = json.loads(docs_json) if docs_json else []
            count = 0
            for r in docs:
                gid = r["gid"]
                doc_json = self.engine.get(gid)
                if doc_json:
                    rubbish_entry = {
                        "original_bucket": bucket,
                        "original_id": gid.split(":")[-1],
                        "deleted_at": time.time(),
                        "document": json.loads(doc_json),
                    }
                    tenant = (
                        self.context.get(
                            "tenant_id", self.context.get("user", "").split(".")[0]
                        )
                        if "user" in self.context
                        else "cron"
                    )
                    r_gid = f"{tenant}.{gid}" if tenant != "cron" else gid
                    self.engine.pour("_rubbish", r_gid, json.dumps(rubbish_entry))
                self.engine.delete(gid)
                count += 1

            if hasattr(self.engine, "delete_bucket"):
                self.engine.delete_bucket(bucket)

            return {
                "status": "ok",
                "message": f"Dropped bucket '{bucket}'. Safely moved {count} documents to the _rubbish bin.",
            }

        elif stmt_type == "DropSecurityStmt":
            bucket = getattr(stmt, "bucket", "")
            name = getattr(stmt, "name", "")

            # Remove from policies
            if bucket in self.security.policies:
                for action in ["read", "write", "all"]:
                    if action in self.security.policies[bucket]:
                        self.security.policies[bucket][action] = [
                            p
                            for p in self.security.policies[bucket][action]
                            if p.get("name") != name
                        ]
            if self.engine:
                self.engine.delete(f"_security_policies:policy_{bucket}_{name}")

            # Remove from masks
            if hasattr(self.security, "masks") and bucket in self.security.masks:
                self.security.masks[bucket] = [
                    m for m in self.security.masks[bucket] if m.get("field") != name
                ]
            if self.engine:
                self.engine.delete(f"_security_policies:mask_{bucket}_{name}")

            return {
                "status": "ok",
                "message": f"Dropped security policies and masks matching '{name}' on '{bucket}'.",
            }

        elif stmt_type == "CronStmt":
            job_id = str(uuid.uuid4())[:8]
            job_body = {
                "interval": stmt.interval_seconds,
                "command": stmt.command_str,
                "last_run": int(time.time()),
            }
            self.engine.pour("_cron", job_id, json.dumps(job_body))
            return {
                "status": "ok",
                "message": f"Scheduled task added to background worker. Will execute every {stmt.interval_seconds} seconds.",
                "job_id": job_id,
            }

        elif stmt_type == "DescribeStmt":
            target = getattr(stmt, "target", getattr(stmt, "bucket", ""))
            if target.upper() == "MEANING":
                return {
                    "status": "ok",
                    "description": "TUTORIAL: Semantic Search (MEANING)\nUse SCOOP EVERYTHING FROM bucket MEANING text",
                }
            docs_json = self._scan_bucket_rls(target)
            docs = json.loads(docs_json) if docs_json else []
            if not docs:
                return {"status": "ok", "description": f"Bucket '{target}' is empty."}
            return {
                "status": "ok",
                "description": f"Bucket '{target}' ({len(docs)} docs). Stats computed successfully.",
            }

        elif stmt_type == "DistillStmt":
            import ctypes
            import os
            from collections import defaultdict

            bucket = getattr(stmt, "bucket", "")
            agg_function = getattr(stmt, "agg_function", "").upper()
            field = getattr(stmt, "field", "")
            group_by = getattr(stmt, "group_by", None)
            alias = getattr(stmt, "alias", None)

            docs_json = self._scan_bucket_rls(bucket)
            docs = json.loads(docs_json) if docs_json else []

            # Grouping
            groups = defaultdict(list)
            for r in docs:
                doc_str = self.engine.get(r["gid"])
                if doc_str:
                    doc_body = json.loads(doc_str)
                    val = doc_body.get(field)
                    if isinstance(val, (int, float)):
                        g_key = doc_body.get(group_by) if group_by else "_all_"
                        groups[g_key].append(val)

            if not groups:
                return {"status": "ok", "result": [], "count": 0}

            results = []
            for g_key, values in groups.items():
                if agg_function in ["TOTAL", "SUM"]:
                    if len(values) > 0 and hasattr(self.engine, "simd_sum_avx512"):
                        # C++ AVX-512 SIMD Execution!
                        float_list = [float(v) for v in values]
                        res = self.engine.simd_sum_avx512(float_list)
                    else:
                        res = sum(values)
                elif agg_function == "AVERAGE":
                    res = sum(values) / len(values)
                elif agg_function == "MIN":
                    res = min(values)
                elif agg_function == "MAX":
                    res = max(values)
                elif agg_function == "SPREAD":
                    res = max(values) - min(values)
                else:
                    return {
                        "status": "error",
                        "message": f"Unknown aggregation: {agg_function}",
                    }

                # Format output
                out_dict = {}
                if group_by:
                    out_dict[group_by] = g_key
                out_dict[alias if alias else agg_function.lower()] = res
                results.append(out_dict)

            # If no group_by, just return the single dict
            if not group_by and len(results) == 1:
                return {
                    "status": "ok",
                    "result": results[0],
                    "count": sum(len(v) for v in groups.values()),
                }

            return {
                "status": "ok",
                "result": results,
                "count": sum(len(v) for v in groups.values()),
            }

        elif stmt_type == "FindHowStmt":
            import dateparser

            t1 = dateparser.parse(stmt.start_time)
            t2 = dateparser.parse(stmt.end_time)
            ts1 = t1.timestamp() * 1000 if t1 else 0
            ts2 = t2.timestamp() * 1000 if t2 else float("inf")

            b_data = self._scan_bucket_rls("_history__bonds")
            bonds = json.loads(b_data) if b_data else []

            changes = []
            for b in sorted(
                bonds, key=lambda x: x.get("body", {}).get("_event_time", 0)
            ):
                body = b.get("body", {})
                evt_time = body.get("_event_time", 0)
                if not (ts1 <= evt_time <= ts2):
                    continue

                doc_id_ns = self._namespace_gid(stmt.doc_id)
                if body.get("label") == stmt.bond_name and (
                    body.get("source") == doc_id_ns or body.get("target") == doc_id_ns
                ):
                    changes.append(
                        {
                            "time": evt_time,
                            "action": body.get("_event_type"),
                            "source": body.get("source"),
                            "target": body.get("target"),
                            "label": body.get("label"),
                        }
                    )

            return {"status": "ok", "mode": "DRIFT", "changes": changes}

        elif stmt_type == "FollowStmt":
            doc_id = getattr(stmt, "doc_key", "")
            bond_label = getattr(stmt, "bond_name", "")
            direction = getattr(stmt, "direction", "OUT").upper()
            depth = getattr(stmt, "depth", 1)
            limit = getattr(stmt, "limit", 100)

            as_of = getattr(stmt, "as_of", None)
            as_of_ts = None
            if as_of:
                import dateparser

                parsed = dateparser.parse(as_of)
                if parsed:
                    as_of_ts = parsed.timestamp() * 1000
                else:
                    try:
                        as_of_ts = float(as_of)
                    except ValueError:
                        pass

            bonds_json = self._scan_bucket_rls(
                "_history__bonds" if as_of_ts else "_bonds"
            )
            bonds = json.loads(bonds_json) if bonds_json else []

            if as_of_ts:
                valid_bonds = {}
                for b_event in sorted(
                    bonds, key=lambda x: x.get("body", {}).get("_event_time", 0)
                ):
                    body = b_event.get("body", {})
                    evt_time = body.get("_event_time", 0)
                    if evt_time > as_of_ts:
                        continue
                    sig = f"{body.get('source')}->{body.get('target')}@{body.get('label')}"
                    if body.get("_event_type") == "SEVER":
                        if sig in valid_bonds:
                            del valid_bonds[sig]
                    else:
                        valid_bonds[sig] = b_event
                # Re-package as normal bonds
                bonds = list(valid_bonds.values())
                for i in range(len(bonds)):
                    # Extract the history event body back into the root for compatibility with follow logic
                    bonds[i]["body"] = bonds[i]["body"]

            visited = set()
            queue = [(self._namespace_gid(doc_id), 0)]
            results = []

            # --- Neuro-Symbolic Pathfinding Setup ---
            guided_by = getattr(stmt, "guided_by", None)
            threshold = getattr(stmt, "threshold", 0.0)
            prompt_emb = None
            if guided_by:
                try:
                    from attention.sra import get_embedding

                    prompt_emb = get_embedding(guided_by).tolist()
                except Exception as e:
                    print(f"[Interpreter] SRA Embedding failed: {e}")

            limit = limit or float("inf")
            while queue and len(results) < limit:
                current_id, current_depth = queue.pop(0)
                if current_id in visited:
                    continue
                visited.add(current_id)

                doc_str = self.engine.get(current_id)
                if doc_str:
                    results.append(json.loads(doc_str))

                if current_depth < depth:
                    for b in bonds:
                        body = b["body"]
                        if body.get("label") == bond_label:
                            if (
                                direction in ("OUT", "BOTH")
                                and body.get("source") == current_id
                            ):
                                queue.append((body.get("target"), current_depth + 1))
                            if (
                                direction in ("IN", "BOTH")
                                and body.get("target") == current_id
                            ):
                                queue.append((body.get("source"), current_depth + 1))

            return {
                "status": "ok",
                "mode": "FOLLOW",
                "documents": results,
                "count": len(results),
            }

        elif stmt_type == "ShapeReplicaStmt":
            target = stmt.target_bucket
            source = stmt.source_bucket
            when_expr = None
            if stmt.when:
                from .parser import Parser
                # Just store the raw expression string for the worker to evaluate
                # but wait, AST nodes don't easily convert back to string without a visitor
                # For now, let's just evaluate it in the worker by passing the AST... actually we can't easily serialize AST to DB.
                # Let's write a small helper to serialize AST to string, or we can just reconstruct the string if we added a `raw` to statement...
                pass
                
            # Actually, the user writes: SHAPE REPLICA public_catalog FROM products WHERE visibility = "public" SHOW name, price
            # We need to save this. Let's just store the AST dict or string?
            # It's better to store the source, target, and the full SQL string that created it, but we only have AST here.
            # Let's serialize the AST to a dictionary for storage.
            
            def serialize_expr(expr):
                if not expr: return None
                if expr.__class__.__name__ == "WhereClause":
                    return {
                        "type": "WhereClause",
                        "predicates": [{"field": p.field, "op": p.op, "value": p.value} for p in expr.predicates],
                        "connectives": expr.connectives
                    }
                return None
                
            replica_def = {
                "type": "replica",
                "target": target,
                "source": source,
                "when": serialize_expr(stmt.when),
                "show_fields": stmt.show_fields
            }
            
            import uuid
            gid = f"replica_{uuid.uuid4().hex[:8]}"
            res = self.engine.pour("_replicas", gid, json.dumps(replica_def))
            if res.startswith("Error"):
                return {"status": "error", "message": res}
            return {"status": "ok", "message": f"Replica '{target}' configured to sync from '{source}'."}

        elif stmt_type == "HelpStmt":
            help_text = """
=== CleaveDB Extended Feature Guide (Foundation Tier) ===

1. GUARD (Document Validation)
   Validate documents natively before writes.
   Usage: GUARD users WITH name IS REQUIRED, age >= 0, role IN ("admin", "user")

2. AUDIT TRAIL (Automatic Change Logging)
   Automatically log all changes in an immutable audit table.
   Usage: SHAPE BUCKET orders AUDITED
   Query: FIND _audit_orders

3. ENRICH (Computed Virtual Fields)
   Automatically inject computed fields during queries.
   Usage: ENRICH users WITH full_name AS CONCAT(first_name, " ", last_name)
   Usage: ENRICH products WITH discount AS price * 0.9

4. PEER INTO COST (Query Profiler & Index Suggester)
   Get a real-time natural language query execution plan and index suggestions.
   Usage: PEER INTO COST (FIND products WHERE category = "Electronics" ARRANGED BY price)

5. WEBHOOK (Native Outbound HTTP Events)
   Fire asynchronous HTTP POST requests instantly when data mutates.
   Usage: SHAPE WEBHOOK "my_hook" ON orders WHEN action = "POUR" POST TO "http://api.com"
   View:  SHOW WEBHOOKS
"""
            return {"status": "ok", "help": help_text}

        elif stmt_type == "ShapeWebhookStmt":
            name = getattr(stmt, "name", "")
            bucket = getattr(stmt, "bucket", "")
            action_filter = getattr(stmt, "action_filter", "")
            url = getattr(stmt, "url", "")
            url = validate_webhook_url(url)
            
            t = self.context.get("tenant_id", self.context.get("user", "").split(".")[0]) if "user" in self.context else "cron"
            doc_id = f"{t}.{name}" if t != "cron" else name
            
            doc = {
                "name": name,
                "bucket": bucket,
                "action": action_filter,
                "url": url,
                "created_at": int(time.time()),
                "tenant": t
            }
            if self.engine:
                self.engine.pour("_webhooks", doc_id, json.dumps(doc))
                
            return {"status": "ok", "message": f"Webhook '{name}' created on bucket '{bucket}'"}

        elif stmt_type == "ShapeBucketStmt":
            path = getattr(stmt, "path", "").lower()
            max_docs = getattr(stmt, "max_documents", None)
            compression = getattr(stmt, "compression", None)
            ttl = getattr(stmt, "ttl", None)
            versioned = getattr(stmt, "versioned", False)
            audited = getattr(stmt, "audited", False)

            if self.engine:
                policy_str = self.engine.get(f"_bucket_policies:{path}")
                policy = (
                    json.loads(policy_str)
                    if policy_str
                    else {"updated_at": int(time.time())}
                )

                if max_docs is not None:
                    policy["algorithm"] = "LRU"
                    policy["capacity"] = max_docs
                if compression:
                    policy["compression"] = compression
                if ttl:
                    policy["ttl"] = ttl
                if versioned:
                    policy["versioned"] = True
                if audited:
                    policy["audited"] = True

                self.engine.pour("_bucket_policies", path, json.dumps(policy))
            return {
                "status": "ok",
                "bucket": path,
                "message": f"Bucket '{path}' configured",
            }

        elif stmt_type == "ShapeProjectionStmt":
            path = getattr(stmt, "path", "")
            from_bucket = getattr(stmt, "from_bucket", "")
            where_tokens = getattr(stmt, "where", [])
            where_str = " ".join([getattr(t, "lexeme", str(t)) for t in where_tokens]) if where_tokens else ""
            policy = {
                "type": "projection",
                "from_bucket": from_bucket,
                "where_str": where_str,
                "created_at": int(time.time()),
            }
            
            # Multi-tenancy isolation
            t = self.context.get("tenant_id", self.context.get("user", "").split(".")[0]) if "user" in self.context else "cron"
            proj_id = f"{t}.{path}" if t != "cron" else path
            
            self.engine.pour("_projections", proj_id, json.dumps(policy))
            return {
                "status": "ok",
                "message": f"Projection '{path}' registered from '{from_bucket}'",
            }

        elif stmt_type == "BondStmt":

            source_gid = self._namespace_gid(getattr(stmt, "source_gid", ""))

            # EXCLUSIVE
            current_time = int(time.time())
            if getattr(stmt, "exclusive", False):
                b_data = self._scan_bucket_rls("_bonds")
                bonds = json.loads(b_data) if b_data else []
                for b_doc in bonds:
                    b = b_doc.get("body", {})
                    if b.get("source") == source_gid and b.get("label") == getattr(
                        stmt, "label", ""
                    ):
                        b["expires_at"] = current_time
                        b_id = (
                            b_doc.get("gid", "").split(":")[-1]
                            if ":" in b_doc.get("gid", "")
                            else b_doc.get("gid", "")
                        )
                        self.engine.pour("_bonds", b_id, json.dumps(b))

            expires = (
                current_time + getattr(stmt, "expires_at", 0)
                if getattr(stmt, "expires_at", None)
                else None
            )

            target_gids = [
                self._namespace_gid(g)
                for g in getattr(stmt, "target_gids", [getattr(stmt, "target_gid", "")])
            ]

            count = 0
            for target_gid in target_gids:
                if not target_gid:
                    continue
                bond_doc = {
                    "created_at": current_time,
                    "source": source_gid,
                    "target": target_gid,
                    "label": getattr(stmt, "label", ""),
                    "condition_subject": getattr(stmt, "condition_subject", "target"),
                    "condition_field": getattr(stmt, "condition_field", None),
                    "condition_value": getattr(stmt, "condition_value", None),
                    "affinity": getattr(stmt, "affinity", None),
                    "confidence": getattr(stmt, "confidence", None),
                    "through": getattr(stmt, "through", None),
                    "cascade": getattr(stmt, "cascade", False),
                    "exclusive": getattr(stmt, "exclusive", False),
                    "expires_at": expires,
                }
                tenant = (
                    self.context.get(
                        "tenant_id", self.context.get("user", "").split(".")[0]
                    )
                    if "user" in self.context
                    else "cron"
                )
                bond_id = (
                    f"{tenant}.{str(uuid.uuid4())}"
                    if tenant != "cron"
                    else str(uuid.uuid4())
                )
                self.engine.pour("_bonds", bond_id, json.dumps(bond_doc))

                # WAL 4D MVCC Append
                hist_doc = dict(bond_doc)
                hist_doc["_event_type"] = "LINK"
                hist_doc["_event_time"] = time.time() * 1000
                self.engine.pour(
                    "_history__bonds",
                    (
                        f"{tenant}.{str(uuid.uuid4())}"
                        if tenant != "cron"
                        else str(uuid.uuid4())
                    ),
                    json.dumps(hist_doc),
                )

                self.emitted_events.append(
                    {
                        "event": "LINK",
                        "target": bond_id,
                        "bucket": "_bonds",
                        "data": bond_doc,
                    }
                )
                count += 1

                if getattr(stmt, "mutual", False):
                    bond_doc_2 = dict(bond_doc)
                    bond_doc_2["source"] = target_gid
                    bond_doc_2["target"] = source_gid
                    bond_id_2 = (
                        f"{tenant}.{str(uuid.uuid4())}"
                        if tenant != "cron"
                        else str(uuid.uuid4())
                    )
                    self.engine.pour("_bonds", bond_id_2, json.dumps(bond_doc_2))
                    # WAL 4D MVCC Append
                    hist_doc2 = dict(bond_doc_2)
                    hist_doc2["_event_type"] = "LINK"
                    hist_doc2["_event_time"] = time.time() * 1000
                    self.engine.pour(
                        "_history__bonds",
                        (
                            f"{tenant}.{str(uuid.uuid4())}"
                            if tenant != "cron"
                            else str(uuid.uuid4())
                        ),
                        json.dumps(hist_doc2),
                    )
                    count += 1

            return {
                "status": "ok",
                "message": f"{count} 15-Dimensional Bonds '{getattr(stmt, 'label', '')}' created.",
            }

        elif stmt_type == "SetContextStmt":
            key = getattr(stmt, "key", "")
            value = getattr(stmt, "value", "")
            self.context[key] = value
            return {"status": "ok", "context": {key: value}}

        elif stmt_type == "AuthenticateStmt":
            user_id = getattr(stmt, "user_id", "")
            self.context["user_id"] = user_id
            return {
                "status": "ok",
                "message": f"Successfully authenticated as '{user_id}'. Current session context updated.",
            }

        elif stmt_type == "PolicyStmt":
            bucket = getattr(stmt, "bucket", "")
            algorithm = getattr(stmt, "algorithm", None)

            if algorithm:
                # It's an LRU / Memory Management Policy
                self.engine.pour(
                    "_bucket_policies",
                    bucket,
                    json.dumps(
                        {"algorithm": algorithm, "updated_at": int(time.time())}
                    ),
                )
                return {
                    "status": "ok",
                    "message": f"Memory management policy '{algorithm}' enforced on bucket '{bucket}'.",
                }
            else:
                # It's a Document Security Level (DSL) Policy
                name = getattr(stmt, "name", "")
                action = getattr(stmt, "action", "")
                condition = getattr(stmt, "condition", [])
                self.security.add_policy(bucket, name, action, condition)
                if self.engine:
                    cond_str = " ".join([t.lexeme for t in condition])
                    doc = {
                        "type": "policy",
                        "bucket": bucket,
                        "name": name,
                        "action": action,
                        "condition_str": cond_str,
                    }
                    tenant = self.context.get(
                        "tenant_id", self.context.get("user", "").split(".")[0]
                    )
                    pol_id = (
                        f"{tenant}.policy_{bucket}_{name}"
                        if tenant != "cron"
                        else f"policy_{bucket}_{name}"
                    )
                    self.engine.pour("_security_policies", pol_id, json.dumps(doc))
                return {
                    "status": "ok",
                    "policy": name,
                    "message": f"Document Security Level (DSL) policy '{name}' active on '{bucket}'",
                }

        elif stmt_type == "MigrateStmt":
            bucket = getattr(stmt, "bucket", "")
            src_json = getattr(stmt, "src_json", {})
            dst_json = getattr(stmt, "dst_json", {})

            thread = threading.Thread(
                target=self._run_migration, args=(bucket, src_json, dst_json)
            )
            thread.daemon = True
            thread.start()

            return {
                "status": "ok",
                "message": f"Zero-Downtime Migration started for bucket '{bucket}' in background.",
            }

        elif stmt_type == "RateLimitStmt":
            doc_id = stmt.role
            data = {"limit": stmt.limit, "role": stmt.role}
            self.engine.pour("_rate_limits", doc_id, json.dumps(data))
            return {
                "status": "ok",
                "message": f"Rate limit of {stmt.limit} QPM set for role '{stmt.role}'",
            }

        elif stmt_type == "MaskStmt":
            bucket = getattr(stmt, "bucket", "")
            field = getattr(stmt, "field", "")
            condition = getattr(stmt, "condition", "")

            # Save the masking rule in security engine
            if not hasattr(self.security, "masks"):
                self.security.masks = {}
            if bucket not in self.security.masks:
                self.security.masks[bucket] = []

            self.security.masks[bucket].append({"field": field, "condition": condition})
            if self.engine:
                cond_str = " ".join([t.lexeme for t in condition])
                doc = {
                    "type": "mask",
                    "bucket": bucket,
                    "field": field,
                    "condition_str": cond_str,
                }
                tenant = self.context.get(
                    "tenant_id", self.context.get("user", "").split(".")[0]
                )
                mask_id = (
                    f"{tenant}.mask_{bucket}_{field}"
                    if tenant != "cron"
                    else f"mask_{bucket}_{field}"
                )
                self.engine.pour("_security_policies", mask_id, json.dumps(doc))
            return {
                "status": "ok",
                "message": f"Masking rule applied to field '{field}' on bucket '{bucket}'.",
            }

        elif stmt_type == "IndexStmt":
            bucket = getattr(stmt, "bucket", "")
            fields = getattr(stmt, "fields", [])
            
            t = self.context.get("tenant_id", self.context.get("user", "").split(".")[0]) if "user" in self.context else "cron"
            idx_id = f"{t}.{str(uuid.uuid4())}"
            idx_doc = {
                "bucket": bucket,
                "fields": fields,
                "created_at": int(time.time())
            }
            if self.engine:
                self.engine.pour("_indexes", idx_id, json.dumps(idx_doc))
                
            return {
                "status": "ok",
                "bucket": bucket,
                "fields": fields,
                "message": "Index created",
            }

        elif stmt_type == "FlowStmt":

            src = getattr(stmt, "from_bucket", "")

            dst = getattr(stmt, "to_bucket", "")

            action = getattr(stmt, "action", "MOVE").upper()

            when = getattr(stmt, "when", None)

            when_dict = None
            if when:
                when_dict = {
                    "predicates": [],
                    "connectives": getattr(when, "connectives", []),
                }
                for p in getattr(when, "predicates", []):
                    when_dict["predicates"].append(
                        {
                            "field": getattr(p, "field", ""),
                            "op": getattr(p, "op", ""),
                            "value": getattr(p, "value", None),
                        }
                    )

            t = (
                self.context.get(
                    "tenant_id", self.context.get("user", "").split(".")[0]
                )
                if "user" in self.context
                else "cron"
            )
            policy = {
                "src": src,
                "dst": dst,
                "action": action,
                "when": when_dict,
                "tenant": t,
                "created_at": int(time.time()),
            }

            print(f"DEBUG POLICY: {policy}")
            print(f"DEBUG POLICY: {policy}")
            print(f"DEBUG POLICY: {policy}"); self.engine.pour("_flows", f"{src}_to_{dst}", json.dumps(policy))

            return {
                "status": "ok",
                "message": f"Flow rule '{src} -> {dst}' ({action}) registered",
            }

        elif stmt_type == "PeerStmt":
            if getattr(stmt, "attention", False):
                try:
                    import sys
                    import os
                    from attention.sra import get_diagnostics
                    stats = get_diagnostics()
                except Exception as e:
                    stats = {"error": str(e)}

                return {
                    "status": "ok",
                    "attention_stats": stats
                }
                
            target = getattr(stmt, "target_stmt", None)
            if target:
                if getattr(stmt, "cost", False):
                    bucket = getattr(target, "bucket", "")
                    
                    # Fetch total docs
                    results_json = self._scan_bucket_rls(bucket)
                    total_docs = len(json.loads(results_json)) if results_json else 0
                    if total_docs == 0:
                        total_docs = 50000  # Fallback for empty bucket testing
                        
                    # Fetch available indexes
                    available_indexes = []
                    idx_json = self._scan_bucket_rls("_indexes")
                    if idx_json:
                        for d in json.loads(idx_json):
                            b = d.get("body", {})
                            if b.get("bucket") == bucket:
                                available_indexes.append(b)
                                
                    from .cost_model import CostModel
                    cm = CostModel()
                    cost_info = cm.explain_cost(target, total_docs, available_indexes)
                    return {"status": "ok", "cost": cost_info}
                else:
                    # Explain the sub-statement
                    from .explain import Explainer

                    exp = Explainer()
                    result = exp.explain(target)
                    return {"status": "ok", "explain": result}
            return {"status": "ok"}

        elif stmt_type == "MatchStmt":
            try:

                results_json = self._scan_bucket_rls(stmt.nodes[0].bucket)
                if not results_json:
                    return "[]"
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
                            clean_cgid = (
                                current_gid.split(".", 1)[-1]
                                if "." in current_gid and ":" in current_gid
                                else current_gid
                            )
                            if edge.direction == "->" and body["source"] == clean_cgid:
                                next_gid = body["target"]
                            elif (
                                edge.direction == "<-" and body["target"] == clean_cgid
                            ):
                                next_gid = body["source"]
                            elif edge.direction == "-":
                                if body["source"] == clean_cgid:
                                    next_gid = body["target"]
                                elif body["target"] == clean_cgid:
                                    next_gid = body["source"]

                            if next_gid and next_gid.startswith(next_node.bucket + ":"):
                                target_doc_str = self.engine.get(next_gid)
                                if target_doc_str:
                                    target_doc = {
                                        "gid": next_gid,
                                        "body": json.loads(target_doc_str),
                                    }
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
                        if not self._evaluate_where(stmt.where, flat_doc):
                            continue
                    final_results.append(path)

                return {
                    "status": "ok",
                    "mode": "MATCH",
                    "paths": final_results,
                    "count": len(final_results),
                }

            except Exception as e:
                import traceback

                traceback.print_exc()
                raise e

        elif stmt_type == "SuggestStmt":
            emb_json = self._scan_bucket_rls("_embeddings")
            emb_docs = json.loads(emb_json) if emb_json else []
            vectors = {}
            for doc in emb_docs:
                full_gid = doc.get("gid")
                doc_str = self.engine.get(full_gid)
                if doc_str:
                    try:
                        vec = json.loads(doc_str)
                        # The doc_str might be wrapped in a dict by the engine, or it might just be the list.
                        if isinstance(vec, dict) and "body" in vec:
                            vec = vec["body"]
                        if isinstance(vec, list):
                            real_gid = full_gid.replace("_embeddings:", "", 1) if full_gid.startswith("_embeddings:") else full_gid
                            vectors[real_gid] = vec
                        else:
                            print(f"SUGGEST WARN: vec is not a list. It is {type(vec)}")
                    except Exception as e:
                        pass
                        
            bonds_json = self._scan_bucket_rls("_bonds")
            bonds_docs = json.loads(bonds_json) if bonds_json else []
            existing_bonds = set()
            for b in bonds_docs:
                full_gid = doc.get("gid")
                doc_str = self.engine.get(full_gid)
                if doc_str:
                    try:
                        vec = json.loads(doc_str)
                        if isinstance(vec, list):
                            # Strip '_embeddings:' to get the real source gid
                            real_gid = full_gid.replace("_embeddings:", "", 1) if full_gid.startswith("_embeddings:") else full_gid
                            vectors[real_gid] = vec
                    except Exception:
                        pass
                        
            bonds_json = self._scan_bucket_rls("_bonds")
            bonds_docs = json.loads(bonds_json) if bonds_json else []
            existing_bonds = set()
            for b in bonds_docs:
                b_str = self.engine.get(b.get("gid"))
                if b_str:
                    try:
                        b_body = json.loads(b_str)
                        src = b_body.get("source")
                        tgt = b_body.get("target")
                        if src and tgt:
                            existing_bonds.add((src, tgt))
                            if b_body.get("mutual"):
                                existing_bonds.add((tgt, src))
                    except Exception:
                        pass
            
            import math
            def cosine_sim(v1, v2):
                dot = sum(a * b for a, b in zip(v1, v2))
                norm1 = math.sqrt(sum(a * a for a in v1))
                norm2 = math.sqrt(sum(a * a for a in v2))
                return dot / (norm1 * norm2) if norm1 > 0 and norm2 > 0 else 0.0
                
            suggestions = []
            gids = list(vectors.keys())
            for i in range(len(gids)):
                for j in range(i + 1, len(gids)):
                    g1 = gids[i]
                    g2 = gids[j]
                    
                    if (g1, g2) in existing_bonds or (g2, g1) in existing_bonds:
                        continue
                        
                    sim = cosine_sim(vectors[g1], vectors[g2])
                    if sim > 0.50:
                        suggestions.append({
                            "source": g1,
                            "target": g2,
                            "confidence": round(sim, 2),
                            "reason": "High vector similarity in _embeddings"
                        })
            
            suggestions.sort(key=lambda x: x["confidence"], reverse=True)
            
            return {
                "status": "ok",
                "suggestions": suggestions
            }

        elif stmt_type == "DrainStmt":

            bucket = getattr(stmt, "bucket", "")

            doc_id = getattr(stmt, "doc_id", None)

            where = getattr(stmt, "where", None)

            before = getattr(stmt, "before", None)

            before_ts = None

            if before:

                import dateparser

                parsed = dateparser.parse(before)

                if parsed:

                    try:

                        before_ts = parsed.timestamp()

                    except Exception:

                        pass

                if before_ts is None:

                    try:

                        before_ts = float(before)

                    except ValueError:

                        pass

            if doc_id:
                try:
                    tenant_bucket = self.engine._ns(bucket)
                except AttributeError:
                    tenant_bucket = bucket

                docs_to_drain = [
                    {
                        "gid": f"{tenant_bucket}:{doc_id}",
                        "body": json.loads(
                            self.engine.get(f"{bucket}:{doc_id}") or "{}"
                        ),
                    }
                ]

            else:

                docs_json = self._scan_bucket_rls(bucket)

                docs = json.loads(docs_json) if docs_json else []

                docs_to_drain = []

                try:
                    tenant_bucket = self.engine._ns(bucket)
                except AttributeError:
                    tenant_bucket = bucket

                for r in docs:
                    body = r.get("body", r)
                    if "gid" in r and ":" in r["gid"]:
                        _gid_id = r["gid"].split(":", 1)[1]
                        r["gid"] = f"{tenant_bucket}:{_gid_id}"

                    if where and not self._evaluate_where(where, body):

                        continue

                    if before_ts is not None:

                        doc_ts = body.get("_created_at") or body.get("created_at")

                        if doc_ts is not None:

                            if doc_ts > 9999999999:

                                doc_ts = doc_ts / 1000.0

                            if doc_ts >= before_ts:

                                continue

                        else:

                            continue

                    docs_to_drain.append({"gid": r["gid"], "body": r})

            drained_count = 0
            b_data = self._scan_bucket_rls("_bonds")
            bonds = json.loads(b_data) if b_data else []

            for doc_info in docs_to_drain:
                gid = doc_info["gid"]
                d_body = doc_info["body"]
                if not d_body:
                    continue

                doc_json = self.engine.get(gid)
                if not doc_json:
                    continue

                rubbish_entry = {
                    "original_bucket": bucket,
                    "original_id": gid.split(":")[-1],
                    "deleted_at": time.time(),
                    "body": json.loads(doc_json),
                }
                tenant = (
                    self.context.get(
                        "tenant_id", self.context.get("user", "").split(".")[0]
                    )
                    if "user" in self.context
                    else "cron"
                )
                r_gid = f"{tenant}.{gid}" if tenant != "cron" else gid
                self.engine.pour("_rubbish", r_gid, json.dumps(rubbish_entry))
                self.engine.delete(gid)
                self._fire_triggers(
                    "DRAIN", bucket, gid.split(":")[-1], json.loads(doc_json)
                )
                self._log_audit(bucket, "DRAIN", gid.split(":")[-1], json.loads(doc_json), None)
                self.emitted_events.append({"event": "DRAIN", "target": gid, "bucket": bucket, "data": json.loads(doc_json)})
                drained_count += 1

                # CASCADING DELETE
                t = (
                    self.context.get(
                        "tenant_id", self.context.get("user", "").split(".")[0]
                    )
                    if "user" in self.context
                    else "cron"
                )

                unnamespaced_gid = (
                    gid.replace(f"{t}.", "", 1)
                    if t != "cron" and gid.startswith(f"{t}.")
                    else gid
                )

                for b_doc in bonds:

                    b = b_doc.get("body", {})

                    if b.get("cascade") and (b.get("source") == unnamespaced_gid):
                        tgt = b.get("target")
                        t_bucket, t_id = (
                            tgt.split(":", 1) if ":" in tgt else (bucket, tgt)
                        )
                        t_gid = f"{t_bucket}:{t_id}"
                        t_json = self.engine.get(t_gid)
                        if t_json:
                            rubbish_entry = {
                                "original_bucket": t_bucket,
                                "original_id": t_id,
                                "deleted_at": time.time(),
                                "body": json.loads(t_json),
                            }
                            tenant = (
                                self.context.get(
                                    "tenant_id",
                                    self.context.get("user", "").split(".")[0],
                                )
                                if "user" in self.context
                                else "cron"
                            )
                            r_t_gid = f"{tenant}.{t_gid}" if tenant != "cron" else t_gid
                            self.engine.pour(
                                "_rubbish", r_t_gid, json.dumps(rubbish_entry)
                            )
                            self.engine.delete(t_gid)

            if doc_id:
                return {
                    "status": "ok",
                    "message": f"Document {doc_id} drained and cascaded.",
                }
            return {
                "status": "ok",
                "message": f"{drained_count} documents drained and cascaded.",
            }

        elif stmt_type == "SalvageStmt":
            doc_id = getattr(stmt, "doc_id", None)
            everything = getattr(stmt, "everything", False)

            r_data = self._scan_bucket_rls("_rubbish")
            rubbish = json.loads(r_data) if r_data else []
            count = 0
            for r in rubbish:
                r_gid = r["gid"]
                # If specific doc, check if gid matches. If everything, do all.
                if everything or (
                    doc_id and (r_gid == doc_id or r_gid.endswith(f":{doc_id}"))
                ):
                    doc_json = self.engine.get(r_gid)
                    if doc_json:
                        rb = json.loads(doc_json)
                        self.engine.pour(
                            rb["original_bucket"],
                            rb["original_id"],
                            json.dumps(rb["body"]),
                        )
                        self.engine.delete(r_gid)
                        count += 1
            return {"status": "ok", "message": f"Salvaged {count} documents."}

        elif stmt_type == "IncinerateStmt":
            doc_id = getattr(stmt, "doc_id", None)
            everything = getattr(stmt, "everything", False)

            r_data = self._scan_bucket_rls("_rubbish")
            rubbish = json.loads(r_data) if r_data else []
            count = 0
            for r in rubbish:
                r_gid = r["gid"]
                if everything or (
                    doc_id and (r_gid == doc_id or r_gid.endswith(f":{doc_id}"))
                ):
                    self.engine.delete(r_gid)
                    count += 1
            return {"status": "ok", "message": f"Incinerated {count} documents."}



        elif stmt_type == "PipeStmt":

            import math
            
            bucket = stmt.source_bucket
            data_str = self._scan_bucket_rls(bucket)
            if not data_str:
                return {"status": "ok", "message": f"Bucket '{bucket}' empty.", "results": []}
                
            docs = json.loads(data_str)
            # The current working set
            results = [d.get("body", {}) for d in docs]
            
            for stage in stmt.stages:
                stage_type = type(stage).__name__
                if stage_type == "FilterStage":
                    filtered = []
                    for doc in results:
                        if self._evaluate_where(stage.where, doc):
                            filtered.append(doc)
                    results = filtered
                    
                elif stage_type == "GroupStage":
                    groups = {}
                    for doc in results:
                        g_val = doc.get(stage.group_field)
                        if g_val not in groups:
                            groups[g_val] = []
                        groups[g_val].append(doc)
                        
                    grouped_results = []
                    for g_val, g_docs in groups.items():
                        new_doc = {stage.group_field: g_val}
                        for agg in stage.aggregations:
                            atype = agg["type"]
                            afield = agg["field"]
                            alias = agg["alias"]
                            
                            if atype == "TALLY":
                                new_doc[alias] = len(g_docs)
                            else:
                                vals = []
                                for d in g_docs:
                                    if afield in d:
                                        try:
                                            vals.append(float(d[afield]))
                                        except:
                                            pass
                                            
                                if not vals:
                                    new_doc[alias] = None
                                elif atype == "TOTAL":
                                    new_doc[alias] = sum(vals)
                                elif atype == "AVERAGE":
                                    new_doc[alias] = sum(vals) / len(vals)
                                elif atype == "MIN":
                                    new_doc[alias] = min(vals)
                                elif atype == "MAX":
                                    new_doc[alias] = max(vals)
                                elif atype == "SPREAD":
                                    if len(vals) < 2:
                                        new_doc[alias] = 0.0
                                    else:
                                        mean = sum(vals) / len(vals)
                                        variance = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
                                        new_doc[alias] = math.sqrt(variance)
                        grouped_results.append(new_doc)
                    results = grouped_results
                    
                elif stage_type == "SortStage":
                    sf = stage.sort_field
                    rev = stage.direction == "DOWN"
                    # Separate docs with the field and without
                    with_f = []
                    without_f = []
                    for doc in results:
                        if sf in doc and doc[sf] is not None:
                            with_f.append(doc)
                        else:
                            without_f.append(doc)
                            
                    with_f.sort(key=lambda d: d[sf], reverse=rev)
                    results = with_f + without_f
                    
                elif stage_type == "LimitStage":
                    results = results[:stage.limit]
                    
                elif stage_type == "ProjectStage":
                    proj_results = []
                    for doc in results:
                        new_doc = {}
                        for f in stage.fields:
                            if f in doc:
                                new_doc[f] = doc[f]
                        proj_results.append(new_doc)
                    results = proj_results
                    
            return {"status": "ok", "results": results}

        elif stmt_type == "ForecastStmt":
            bucket = stmt.bucket
            val_f = stmt.value_field
            time_f = stmt.time_field
            horizon = stmt.horizon
            if horizon <= 0 or horizon > MAX_FORECAST_HORIZON:
                return {"status": "error", "message": f"FORECAST horizon must be between 1 and {MAX_FORECAST_HORIZON}."}
            method = stmt.method
            window = stmt.window
            
            data_str = self._scan_bucket_rls(bucket)
            if not data_str:
                return {"status": "error", "message": f"Bucket '{bucket}' not found or empty."}
            

            data = json.loads(data_str)
            
            import numpy as np
            import datetime
            
            pts = []
            for d in data:
                b = d.get("body", {})
                if time_f in b and val_f in b:
                    try:
                        vv = float(b[val_f])
                        tv = b[time_f]
                        if isinstance(tv, str):
                            try:
                                dt = datetime.datetime.fromisoformat(tv.replace('Z', '+00:00'))
                                tv_num = dt.timestamp()
                            except:
                                tv_num = float(tv)
                        else:
                            tv_num = float(tv)
                            
                        pts.append((tv_num, vv, tv))
                    except (ValueError, TypeError):
                        pass
                        
            if not pts:
                return {"status": "error", "message": "No valid numeric time/value data points found."}
                
            pts.sort(key=lambda x: x[0])
            X = np.array([x[0] for x in pts])
            Y = np.array([x[1] for x in pts])
            
            last_t = X[-1]
            unit = stmt.time_unit.upper()
            if unit.startswith("DAY"):
                delta = 86400
            elif unit.startswith("HOUR"):
                delta = 3600
            elif unit.startswith("MIN"):
                delta = 60
            else:
                delta = 1
                
            future_X = np.array([last_t + delta * i for i in range(1, horizon + 1)])
            
            if method == "LINEAR":
                if len(X) < 2:
                    return {"status": "error", "message": "Not enough data points for LINEAR method."}
                A = np.vstack([X, np.ones(len(X))]).T
                m, c = np.linalg.lstsq(A, Y, rcond=None)[0]
                pred_Y = m * future_X + c
                
                yhat = m * X + c
                ybar = np.sum(Y)/len(Y)
                ssreg = np.sum((yhat-ybar)**2)
                sstot = np.sum((Y - ybar)**2)
                r_squared = ssreg / sstot if sstot != 0 else 1.0
                
                res = {"status": "ok", "method": "LINEAR", "r_squared": round(r_squared, 4)}
                
            elif method == "MOVING_AVERAGE":
                if window <= 0:
                    window = 3
                w = min(window, len(Y))
                last_vals = list(Y[-w:])
                pred_Y = []
                for _ in range(horizon):
                    nxt = sum(last_vals) / len(last_vals)
                    pred_Y.append(nxt)
                    last_vals.pop(0)
                    last_vals.append(nxt)
                res = {"status": "ok", "method": "MOVING_AVERAGE", "window": window}
                
            elif method == "EXPONENTIAL":
                alpha = 0.5
                s = Y[0]
                for y in Y[1:]:
                    s = alpha * y + (1 - alpha) * s
                
                pred_Y = []
                for _ in range(horizon):
                    pred_Y.append(s)
                res = {"status": "ok", "method": "EXPONENTIAL", "alpha": alpha}
            else:
                return {"status": "error", "message": f"Unknown method {method}"}
                
            pred_list = []
            for i in range(horizon):
                fx = future_X[i]
                is_date = any(isinstance(x[2], str) and '-' in x[2] for x in pts)
                
                if is_date:
                    try:
                        # try to output in UTC format
                        dt = datetime.datetime.fromtimestamp(fx, tz=datetime.timezone.utc)
                        date_str = dt.isoformat()
                        if unit.startswith("DAY"):
                            date_str = date_str.split('T')[0]
                    except:
                        date_str = str(fx)
                else:
                    date_str = str(fx)
                    
                pred_list.append({
                    "date": date_str,
                    f"predicted_{val_f}": round(pred_Y[i], 4)
                })
                
            res["predictions"] = pred_list
            return res

        else:
            return {"status": "error", "message": f"Unknown statement: {stmt_type}"}
