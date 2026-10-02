with open('cleaveql/interpreter.py', 'r', encoding='utf-8') as f:
    text = f.read()

bad_block = """                if self.in_transaction:
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
            return {"status": "ok", "count": len(gids), "gids": gids}"""

good_block = """                if self.in_transaction:
                    self.transaction_log.append({"gid": gid, "body": old_val})

                # --- Vector Indexing Queue ---
                if self.indexing_queue is not None and isinstance(doc, dict):
                    text_content = " ".join([str(v) for v in doc.values() if isinstance(v, str)])
                    if text_content:
                        print(f"[Interpreter] Pushing {gid} to vector queue!"); self.indexing_queue.put((gid, text_content))

                self.emitted_events.append({"event": "POUR", "target": gid, "bucket": bucket, "data": doc})
                gids.append(gid)
            return {"status": "ok", "count": len(gids), "gids": gids}"""

if bad_block in text:
    text = text.replace(bad_block, good_block)
    with open('cleaveql/interpreter.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print("PATCHED")
else:
    print("NOT FOUND")
