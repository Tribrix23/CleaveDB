# CleaveQL Quick Reference — Complete Command Guide

Thirty-two CleaveQL commands, every variant, all bond types, combinations, and chaining recipes.
**Every example was executed against a live CleaveDB instance and returned `status: ok`** (except where an error is shown on purpose).

| # | Command | Purpose | Aliases |
|---|---------|---------|---------|
| 1 | `POUR`     | Create / write documents | — |
| 2 | `SCOOP`    | Read / query structured data with filters | - |
| - | `FIND`     | Search vectors / graphs (Semantic Search, Patterns, Bonds) | `SCOOP` (Alias) |
| 3 | `CHANGE`   | Update fields of a document | `UPDATE` |
| 4 | `DRAIN`    | Soft-delete (moves to `_rubbish`) | — |
| 5 | `BOND`     | Create a semantic graph relationship (edge) between documents (requires `AS "<label>"`) | — |
| - | `LINK`     | Create a direct structural document or external URL reference | — |
| - | `SEVER`    | Sever / remove semantic graph bonds between documents | — |
| - | `UNLINK`   | Remove document or external URL links | — |
| 6 | `SHOW`     | List buckets, bonds, links, indexes, stats, webhooks | — |
| 7 | `DESCRIBE` | Summarise a bucket | — |
| 8 | `SHAPE`    | Configure a bucket (audit, versioning, limits) or register a webhook | — |
| 9 | `GUARD`    | Validation rules enforced on writes | — |
| 10 | `INDEX`   | Create an index on bucket fields | — |
| 11 | `TRACE`   | Walk a chain of bonds from a starting document | — |
| 12 | `FOLLOW`  | Explore the graph neighbourhood of a document | — |
| 13 | `FIND PATTERN` | Pattern-match across buckets and bond edges | — |
| 14 | `DISTILL` | Aggregate a bucket (count, sum, average, min, max, spread, group by, where) | — |
| 15 | `HEAL`    | Repair broken bonds and stale data | — |
| 16 | `SUGGEST BONDS` | Propose bonds you haven't created yet | — |
| 17 | `REWIND`  | Restore a document to how it was at an earlier time | — |
| 18 | `INCINERATE` | Permanently delete from the `_rubbish` bin | — |
| 19 | `DROP`    | Remove a whole bucket (recoverable via `RESTORE`) | — |
| 20 | `RESTORE` | Bring a dropped bucket back from `_rubbish` | — |
| 21 | `MIGRATE` | Reshape every document in a bucket with a pattern | — |
| 22 | `AUTHENTICATE`| Change the current session user | `SET` |
| 23 | `LIMIT`   | Set rate limits (queries per minute) for a role | — |
| 24 | `POLICY`  | Enforce memory eviction rules or access control | `ENFORCE` |
| 25 | `MASK`    | Conditionally redact fields from read queries | — |
| 26 | `EVERY`   | Schedule background repeating commands | `CRON` |
| 27 | `ENRICH`  | Inject computed virtual fields into queries | — |
| 28 | `LISTEN`  | Open a real-time data subscription to a bucket/document | — |
| 29 | `PEER`    | Analyze query execution cost and index usage | — |
| 30 | `SET CONTEXT` | Inject arbitrary key-value pairs into the session context | `SET` |
| 31 | `MATCH`   | Perform Cypher-like advanced graph pattern traversal | — |
| 32 | `UNDO`    | View global operation history and revert past changes | — |

Document IDs are written `bucket:id` (e.g. `"users:jane"`). Bonds use these full IDs.

---

## 1. POUR — create documents

```sql
POUR INTO users "jane" {"name": "Jane", "age": 25, "city": "Manila"}
```

| Variant | Syntax |
|---------|--------|
| Explicit ID | `POUR INTO users "juan" {"name": "Juan"}` |
| Quoted bucket | `POUR INTO "users" "pedro" {"name": "Pedro"}` |
| Auto-generated ID | `POUR INTO users RANDOM {"name": "Rand"}` |
| Bulk insert | `POUR MANY INTO users [{"name": "A"}, {"name": "B"}]` |
| Expiring document (TTL) | `POUR INTO sessions "s1" {"user": "jane"} EXPIRES IN 30 MINUTES` |
| With login secret | `POUR INTO vault "k1" {"token": "abc"} WITH SECRET "mykey"` |
| Write into a nested field | `POUR '{"nick": "JJ"}' INSIDE users "jane" AT profile` |

- TTL units: `SECONDS`, `MINUTES`, `HOURS`, `DAYS`.
- `INSIDE ... AT` takes the JSON as a **quoted string** and sets `profile` on the existing document.
- `POUR MANY` checks `GUARD` rules for **every** document first; if one is rejected, nothing is written.

---

## 2. SCOOP and FIND - Read and Query

In CleaveQL, reading data is done via the `SCOOP` or `FIND` commands. Historically, `FIND` was simply an alias for `SCOOP`. However, they have now been given distinct semantic roles to make your queries read like natural language:

*   **`SCOOP`**: Used for structured querying, filtering, and bulk data retrieval (think SQL `SELECT`).
*   **`FIND`**: Used as a shorthand for Graph queries (e.g., `FIND "friend" OF...`), Pattern matching (`FIND PATTERN...`), and Semantic Vector Searches (`FIND "search text" IN...`).

*Note: Since they share the same underlying AST parser, you can still use them interchangeably (e.g., `SCOOP PATTERN` or `FIND EVERYTHING FROM users`), but adhering to their semantic roles is highly recommended.*

```sql
SCOOP EVERYTHING FROM users
```

### 2a. Documents

| Variant | Syntax |
|---------|--------|
| All documents | `FIND users` · `FIND FROM users` · `FIND EVERYTHING FROM users` |
| By ID | `FIND users "jane"` |
| Filter | `FIND users WHERE age > 20` |
| Multiple conditions | `FIND users WHERE age > 20 AND city = "Manila"` |
| OR | `FIND users WHERE age < 20 OR city = "Cebu"` |
| Exact field | `FIND users WHOSE name IS "Jane"` |
| JSON match | `FIND users MATCHING {"city": "Manila"}` |
| Sort | `FIND users ARRANGED BY age GOING DOWN` (also `ORDER BY … GOING UP`, `SORTED BY age DESC`) |
| Limit | `FIND users LIMIT 2` |
| Pick fields | `FIND users YIELD name, age` (also `SHOW name`) |
| Combined | `FIND users WHERE age > 10 ARRANGED BY age GOING DOWN LIMIT 2` |

Operators: `=`, `!=`, `>`, `<`, `>=`, `<=`, joined with `AND` / `OR`.

### 2b. Summaries

| Variant | Syntax |
|---------|--------|
| Distinct values | `FIND ONLY UNIQUE city FROM users` |
| First N / last N | `FIND THE FIRST 2 FROM users` · `FIND THE LAST 2 FROM users` |
| Count | `FIND THE TALLY OF users` |
| Top N by field | `FIND THE HIGHEST 2 age FROM users` |
| Bottom N by field | `FIND THE LOWEST 2 age FROM users` |

### 2c. Bonds (graph lookups)

| Variant | Syntax |
|---------|--------|
| Related docs | `FIND "crush" OF "users:jane"` |
| Legacy form | `FIND RELATED "friend" FROM "users:jane"` |
| Include inactive conditional bonds | `FIND CANDIDATE "cond" OF "users:jane"` |
| Bonds as they were | `FIND "friend" OF "users:jane" AS OF "yesterday"` |
| Multi-hop chain | `FIND THE knows OF THE boss OF users "jane"` |

Notes:
- Results are de-duplicated by target document.
- Documents that were `DRAIN`ed (sitting in `_rubbish`) are **not** returned.
- A chain reads right-to-left: the label closest to the bucket is followed first. `FIND THE knows OF THE boss OF users "jane"` = *whom does Jane's boss know?*

---

## 3. CHANGE — update fields

```sql
CHANGE users "jane" SET age TO 26
```

| Variant | Syntax |
|---------|--------|
| Single field | `CHANGE users "jane" SET age TO 26` |
| Multiple fields | `CHANGE users "jane" SET age TO 27, city TO "Quezon"` |
| ID-first form | `CHANGE "jane" IN users TO age = 28` |
| ID-first, multiple | `CHANGE "jane" IN users SET age = 29, city = "Makati"` |
| Alias | `UPDATE users "juan" SET age TO 31` |

- Only the listed fields change; the rest of the document is preserved.
- `GUARD` rules are enforced on `CHANGE` too.
- Negative numbers aren't accepted as `CHANGE` values (`SET age TO -5` is a parse error); use `POUR` with the full document instead.

---

## 4. DRAIN — soft-delete

```sql
DRAIN users "pedro"
```

| Variant | Syntax |
|---------|--------|
| One document | `DRAIN users "pedro"` |
| By condition | `DRAIN users WHERE age < 5` |
| By condition (AND / OR) | `DRAIN emp WHERE dept = "HR" AND age > 26` · `DRAIN emp WHERE age < 20 OR dept = "Ops"` |
| By age | `DRAIN users BEFORE "2000-01-01"` |

Drained documents go to `_rubbish` and their bonds are cascaded. Companions:

| Command | Effect |
|---------|--------|
| `SALVAGE "pedro"` | Restore one drained document (its bonds come back too) |
| `SALVAGE EVERYTHING` | Restore all drained documents |
| `INCINERATE "pedro"` | Permanently delete one from `_rubbish` |
| `INCINERATE EVERYTHING` | Empty `_rubbish` |

---

## 5. BOND & LINK — Relationships and References

CleaveDB provides two distinct relationship mechanisms with different architectures, semantics, and capabilities:
- **`BOND`**: Rich semantic graph relationships (edges) stored in `_bonds`. A bond **requires an explicit relationship label** via `AS "<label>"` (e.g. `AS "friend"`). Bonds represent graph meaning and support dynamic weights (`WITH CONFIDENCE`, `WITH AFFINITY`), conditions (`IF`, `ONLY WHEN`), TTL (`EXPIRING IN`), `MUTUAL`, and `EXCLUSIVELY`. Removed with `SEVER`.
- **`LINK`**: Direct structural document or external URL references stored in `_links`. Does not require a relationship label (defaults to `"linked"`) and cannot take graph modifiers like weights or conditions. Removed with `UNLINK`.
- **Clean Terminology**: The legacy term "15-Dimensional Bond" has been completely removed in favor of clean **"Graph Bond"** terminology.
- **Strict Existence Validation**: Both source and target buckets and documents must exist prior to creating bonds or links (external URLs are validated as URLs and exempt from local bucket checks). Creating ghost edges on non-existent buckets or documents is strictly rejected.

### Summary Comparison: BOND vs LINK

| Feature | `BOND` (Graph Relationship) | `LINK` (Document / URL Reference) |
|---|---|---|
| **Primary Purpose** | Semantic graph relationships with meaning (edges) | Direct document / external URL references |
| **Relationship Label** | **Required** via `AS "<label>"` (e.g. `AS "friend"`) | **Optional** (defaults to `"linked"`) |
| **Internal Storage** | Dedicated `_bonds` bucket | Dedicated `_links` bucket |
| **External URL Targets** | No (internal document GIDs only) | **Yes** (supports `https://...`, `http://...`) |
| **Confidence & Affinity** | **Yes** (`WITH CONFIDENCE`, `WITH AFFINITY`) | No (rejected by parser) |
| **TTL Expiry** | **Yes** (`EXPIRING IN <n> SECONDS/MINUTES/HOURS`) | No |
| **Conditional Activation**| **Yes** (`IF <field> = <val>`, `ONLY WHEN`) | No |
| **Exclusivity** | **Yes** (`EXCLUSIVELY` replaces previous target) | No |
| **Cascade on Delete** | **Yes** (`ON DELETE CASCADE`) | No |
| **Graph Querying** | `FIND "<label>" OF <doc>`, `FOLLOW`, `TRACE`, `FIND PATTERN`, `MATCH`, `SHOW BONDS` | `FIND LINKS OF <doc>`, `SHOW LINKS` |
| **Removal Command** | `SEVER <doc1> FROM <doc2> [AS "<label>"]` | `UNLINK <doc1> FROM <doc2>` |
| **Maintenance / Healing**| `HEAL BONDS`, `HEAL ALL` | `HEAL LINKS`, `HEAL ALL` |

---

### 5a. BOND — Semantic Graph Relationships

A bond represents a directed (or mutual) semantic relationship between two existing documents in the database.

```sql
BOND "users:jane" TO "users:juan" AS "crush"
```

| Form | Syntax | Description |
|------|--------|-------------|
| Labelled bond (**Required**) | `BOND "users:jane" TO "users:juan" AS "friend"` | Creates a graph edge with the given label |
| Several targets | `BOND "users:jane" TO "users:juan", "users:pedro" AS "knows"` | Bonds source to multiple target documents |
| `ANY(...)` targets | `BOND "users:jane" TO ANY("users:juan", "users:pedro") AS "knows"` | Bonds source to each listed target |
| Two-way (mutual) | `BOND "users:jane" AND "users:pedro" AS MUTUAL "bff"` | Creates bidirectional bonds between both documents |

> **Requirement:** `BOND` **always** requires `AS "<label>"`. If you omit `AS`, the command is rejected:
> ```
> cleave> BOND "user:alice" TO "user:david"
> [{"status": "error", "message": "Error at '': BOND requires an explicit relationship label using AS \"<label>\" (e.g. BOND \"user:alice\" TO \"user:bob\" AS \"friend\"). Use LINK for unlabelled document links."}]
> ```

---

### 5b. LINK — Direct Document & URL References

A link represents a structural pointer to another document or an external web resource.

```sql
LINK "users:jane" TO "users:juan"
LINK "users:jane" TO "https://github.com/jane"
```

| Form | Syntax | Description |
|------|--------|-------------|
| Unlabelled document link | `LINK "users:jane" TO "users:juan"` | Links two documents (label defaults to `"linked"`) |
| Labelled document link | `LINK "users:jane" TO "users:juan" AS "mentor"` | Custom label on a lightweight link |
| External URL reference | `LINK "users:jane" TO "https://github.com/jane"` | Links an internal document to an external URL |
| Two-way (mutual) link | `LINK "users:jane" AND "users:pedro" AS MUTUAL` | Creates bidirectional links |
| Multiple targets | `LINK "users:jane" TO ANY("users:juan", "users:pedro")` | Links source to multiple targets |

> **Note:** `LINK` targets may be web URLs (`http://` or `https://`). Bond modifiers such as `WITH`, `IF`, and `EXPIRING` are not supported on `LINK` and will produce a parse error directing you to `BOND`.

---

### 5c. Existence Validation — Preventing Ghost Relationships

CleaveDB verifies that buckets and documents exist **before** any relationship is created:

```text
cleave> SHOW BUCKETS
[{"status": "ok", "data": []}]

cleave> BOND "user:alice" TO "user:david" AS "friend"
[{"status": "error", "message": "Source bucket 'user' does not exist."}]

cleave> LINK "user:alice" TO "user:david"
[{"status": "error", "message": "Source bucket 'user' does not exist."}]
```

Once documents are written with `POUR`, bonds and links succeed:

```text
cleave> POUR INTO user "alice" {"name": "Alice"}
cleave> POUR INTO user "david" {"name": "David"}
cleave> BOND "user:alice" TO "user:david" AS "friend"
[{"status": "ok", "message": "1 Graph Bond 'friend' created."}]

cleave> LINK "user:alice" TO "user:david"
[{"status": "ok", "message": "1 Document Link created."}]
```

---

### 5d. Bond Modifiers

Modifiers may be appended after `AS "label"` on `BOND`. Multiple modifiers can be combined on a single statement:

| Modifier | Syntax | Effect |
|----------|--------|--------|
| Confidence score | `WITH CONFIDENCE 0.9` | Stores a 0–1 strength score on the bond |
| Affinity score | `WITH AFFINITY 0.8` | Stores a 0–1 closeness score on the bond |
| Both scores | `WITH CONFIDENCE 0.9 WITH AFFINITY 0.7` | Combines both scores on one bond |
| Expiry (seconds) | `EXPIRING IN 30 SECONDS` | Bond automatically expires after 30 s |
| Expiry (minutes) | `EXPIRING IN 5 MINUTES` | Bond automatically expires after 5 min |
| Expiry (hours) | `EXPIRING IN 2 HOURS` | Bond automatically expires after 2 h |
| Exclusive | `EXCLUSIVELY` | Replaces any previous bond with the same label from this source |
| Cascade on delete | `ON DELETE CASCADE` | When the source is `DRAIN`ed, target document is also drained |
| Through bucket | `THROUGH hubs` | Tags the bond with an intermediate bucket reference |

---

### 5e. Conditional Bonds

Bonds can be defined with activation conditions that are dynamically evaluated against document fields. If the condition is false, the bond remains dormant:

| Condition | Syntax | Checked against |
|-----------|--------|-----------------|
| Target field (default) | `IF status = "active"` | Target document's field |
| `ONLY WHEN` synonym | `ONLY WHEN status IS "active"` | Target document's field |
| Source field (`source`) | `IF source role IS "admin"` | Source document's field |
| Source field (`my`) | `IF my role = "admin"` | Source document's field |
| Target field (`their`) | `IF their role = "user"` | Target document's field |
| Numeric field | `IF age = 25` | Target document's field |

**How conditional bonds behave:**

```sql
-- Create a conditional bond
BOND "staff:a" TO "staff:d" AS "gate" IF status = "active"

-- staff:d status is "active" → bond is live
FIND "gate" OF "staff:a"                -- 1 result

-- Change target field so condition fails
CHANGE staff "d" SET status TO "inactive"
FIND "gate" OF "staff:a"                -- 0 results (inactive)
FIND CANDIDATE "gate" OF "staff:a"      -- shows the bond with status "candidate"

-- Restore target field → bond activates again automatically
CHANGE staff "d" SET status TO "active"
FIND "gate" OF "staff:a"                -- 1 result again
```

---

### 5f. Fully-Loaded Bond (All Modifiers at Once)

```sql
BOND "staff:a" TO "staff:b" AS "full"
  IF status = "active"
  WITH CONFIDENCE 0.9
  EXPIRING IN 2 HOURS
  ON DELETE CASCADE
  EXCLUSIVELY
```

---

### 5g. Special Bond Cases

| Case | Syntax | Behaviour |
|------|--------|-----------|
| Self-referencing | `BOND "users:ann" TO "users:ann" AS "self"` | Document bonds to itself (document must exist) |
| Missing document | `BOND "users:ann" TO "users:ghost" AS "ghost"` | Rejected with error: `Target document 'users:ghost' does not exist in bucket 'users'.` |
| Missing bucket | `BOND "missing:1" TO "users:ann" AS "rel"` | Rejected with error: `Source bucket 'missing' does not exist.` |
| Duplicate bonds | `BOND "a:1" TO "a:2" AS "dup"` twice | Both stored; `FIND` deduplicates by target |

---

### 5h. Exclusive Bonds — Replacing Previous Targets

```sql
BOND "staff:a" TO "staff:b" AS "primary" EXCLUSIVELY
BOND "staff:a" TO "staff:c" AS "primary" EXCLUSIVELY   -- replaces the a→b bond
FIND "primary" OF "staff:a"                             -- returns only staff:c
```

---

### 5i. Expiring Bonds (TTL)

```sql
BOND "staff:a" TO "staff:b" AS "temp" EXPIRING IN 1 SECONDS
FIND "temp" OF "staff:a"      -- 1 result (immediately after)
-- wait 2 seconds …
FIND "temp" OF "staff:a"      -- 0 results (expired)
```

---

### 5j. Cascade on Delete

```sql
BOND "staff:a" TO "staff:b" AS "cascade_demo" ON DELETE CASCADE
DRAIN staff "a"                -- drains staff:a AND cascades to drain staff:b
```

---

### 5k. Removing Relationships — SEVER vs UNLINK

Bonds and links have dedicated removal commands:

#### SEVER — Remove Bonds
```sql
SEVER "users:jane" FROM "users:juan" AS "friend"
```

| Variant | Syntax | Effect |
|---------|--------|--------|
| One label | `SEVER "users:jane" FROM "users:juan" AS "friend"` | Removes bonds with matching label between the pair |
| All labels between pair | `SEVER "users:jane" FROM "users:juan"` | Removes all bonds between the two documents in either direction |

#### UNLINK — Remove Links
```sql
UNLINK "users:jane" FROM "users:juan"
UNLINK "users:jane" FROM "https://github.com/jane"
```

| Variant | Syntax | Effect |
|---------|--------|--------|
| Document link | `UNLINK "users:jane" FROM "users:juan"` | Removes links between the two documents |
| Labelled link | `UNLINK "users:jane" FROM "users:juan" AS "mentor"` | Removes specific labelled link |
| URL link | `UNLINK "users:jane" FROM "https://github.com/jane"` | Removes link to external URL |

---

### 5l. Node Disappearance and Healing

When a document is deleted via `DRAIN`, CleaveDB automatically detaches any bonds or links connected to it.

To repair existing databases or prune any orphaned relationships left from external operations:

| Command | Effect |
|---------|--------|
| `HEAL BONDS` | Scans `_bonds` and removes any edge whose source or target document no longer exists |
| `HEAL LINKS` | Scans `_links` and removes any link whose source or target document no longer exists |
| `HEAL ALL` | Performs full healing across bonds, links, and indexes |

---

## 6. SHOW — list things

| Syntax | Returns |
|--------|---------|
| `SHOW BUCKETS` | Your bucket names: `{"data": ["emp", "mix"]}` |
| `SHOW BONDS` | Every semantic graph bond: `{"count": 1, "data": [{…}]}` |
| `SHOW LINKS` | Every document / URL link: `{"count": 1, "data": [{…}]}` |
| `SHOW INDEXES` | Every index: `{"count": 1, "data": [{…}]}` |
| `SHOW STATS` | Totals: `{"buckets": 1, "documents": 3, "bonds": 1, "per_bucket": {"emp": 3}}` |
| `SHOW WEBHOOKS` | Webhooks: `{"count": 1, "data": [{…}]}` |

Results only include your own data. Internal `_` buckets are hidden unless you log in with the dev password.

---

## 7. DESCRIBE — summarise a bucket

```sql
DESCRIBE emp
```
Returns e.g. `Bucket 'emp' (7 docs). Stats computed successfully.` A bucket with no documents returns `Bucket 'nosuch' is empty.`

---

## 8. SHAPE — configure buckets and webhooks

```sql
SHAPE BUCKET orders AUDITED
```

| Variant | Syntax |
|---------|--------|
| Audit every change | `SHAPE BUCKET orders AUDITED` |
| Keep versions | `SHAPE BUCKET orders VERSIONED` |
| Cap document count | `SHAPE BUCKET orders MAX DOCUMENTS 100` |
| Compression | `SHAPE BUCKET orders COMPRESSION zstd` |
| Expiry | `SHAPE BUCKET orders TTL 3600` |
| Several at once | `SHAPE BUCKET orders VERSIONED AUDITED MAX DOCUMENTS 50` |
| Short form | `SHAPE orders AUDITED` |
| Webhook on writes | `SHAPE WEBHOOK "hook1" ON orders WHEN ACTION = "POUR" POST TO "http://example.com/hook"` |

- Each option updates the bucket's saved policy; repeating `SHAPE` adds to it.
- With `AUDITED`, changes are logged to `_audit_<bucket>` (e.g. `FIND _audit_orders`). Reading it **requires the dev password**; a normal login gets `Access Denied`.
- List webhooks with `SHOW WEBHOOKS`.

---

## 9. GUARD — validation rules

```sql
GUARD people WITH name IS REQUIRED, age >= 0, role IN ("admin", "user")
```

| Rule | Syntax |
|------|--------|
| Field must exist | `name IS REQUIRED` |
| Field must not exist | `nick IS NOT REQUIRED` |
| Comparison | `age >= 0` (also `>`, `<`, `<=`, `=`, `!=`) |
| One of a list | `role IN ("admin", "user")` |
| Type check | `age IS TYPE number` |

Rules are comma-separated, and later `GUARD` statements for the same bucket **add** to the existing rules. Once set, violating writes are rejected:

```text
POUR INTO people "p2" {"age": 5, "role": "user"}
  → Guard violation on 'people': 'name' is required
POUR INTO people "p3" {"name": "Neg", "age": -1, "role": "user"}
  → Guard violation on 'people': 'age' must be >= 0
POUR INTO people "p4" {"name": "BadRole", "age": 5, "role": "boss"}
  → Guard violation on 'people': 'role' must be one of ['admin', 'user']
```

Enforced on `POUR`, `POUR MANY` and `CHANGE`.

---

## 10. INDEX — speed up lookups

```sql
INDEX age ON emp
```

| Variant | Syntax |
|---------|--------|
| One field | `INDEX age ON emp` · `INDEX emp ON (age)` |
| Several fields | `INDEX dept, age ON emp` · `INDEX emp ON (dept, age)` |

Check with `SHOW INDEXES`. Running the same `INDEX` twice creates a duplicate entry.

---

## 11. TRACE — walk a bond chain

Follow a sequence of labelled bonds from a starting document, returning every document visited along the way.

```sql
TRACE "reports_to" FROM "staff:bob"
```

| Variant | Syntax | Effect |
|---------|--------|--------|
| Single label | `TRACE "reports_to" FROM "staff:bob"` | Walk `reports_to` edges one hop at a time until there are no more |
| Multi-label chain | `TRACE "reports_to", "reports_to" FROM "staff:bob"` | Walk exactly 2 hops of `reports_to` |
| Mixed labels | `TRACE "manages", "mentors" FROM "staff:ana"` | First hop follows `manages`, second hop follows `mentors` |

```sql
-- Setup: bob →reports_to→ di →reports_to→ cy
BOND "staff:bob" TO "staff:di" AS "reports_to"
BOND "staff:di" TO "staff:cy" AS "reports_to"

TRACE "reports_to" FROM "staff:bob"
-- Returns the chain: bob → di → cy

TRACE "reports_to", "reports_to" FROM "staff:bob"
-- Same result, but explicitly asks for exactly 2 hops
```

---

## 12. FOLLOW — explore graph neighbourhood

Explore which documents are reachable from a starting point, optionally filtering by bond label, direction, and depth.

```sql
FOLLOW "staff:ana" THROUGH "manages"
```

| Variant | Syntax |
|---------|--------|
| All bonds (any label) | `FOLLOW "staff:ana"` |
| Through a specific label | `FOLLOW "staff:ana" THROUGH "manages"` |
| Unquoted label | `FOLLOW "staff:ana" THROUGH manages` |
| Outgoing only | `FOLLOW "staff:ana" THROUGH "manages" DIRECTION OUT` |
| Incoming only | `FOLLOW "staff:bob" THROUGH "manages" DIRECTION IN` |
| Both directions | `FOLLOW "staff:ana" THROUGH "manages" DIRECTION BOTH` |
| Multi-hop depth | `FOLLOW "staff:bob" THROUGH "reports_to" DEPTH 2` |
| Depth + limit | `FOLLOW "staff:bob" THROUGH "reports_to" DEPTH 2 LIMIT 1` |
| Sort results | `FOLLOW "staff:ana" THROUGH "manages" ARRANGED BY age GOING DOWN LIMIT 2` |
| Historical view | `FOLLOW "staff:ana" THROUGH "manages" AS OF "yesterday"` |

```sql
-- ana manages bob and cam; bob reports_to cam
FOLLOW "staff:ana" THROUGH "manages"
-- Returns: bob, cam (1 hop out)

FOLLOW "staff:bob" THROUGH "manages" DIRECTION IN
-- Returns: ana (who manages bob)

FOLLOW "staff:bob" THROUGH "reports_to" DEPTH 2
-- Returns: cam, dee (2-hop chain)
```

---

## 13. FIND PATTERN — graph pattern matching

Match subgraph patterns across buckets and bond edges. Each node is aliased (`AS x`), and you specify the bond label with `LINKED VIA`.

```sql
FIND PATTERN IN staff AS x LINKED VIA "manages" TO staff AS y
```

### Edge directions

| Direction | Syntax | Meaning |
|-----------|--------|---------|
| Outgoing (`→`) | `… LINKED VIA "manages" TO staff AS y` | x manages y |
| Incoming (`←`) | `… LINKED VIA "manages" FROM staff AS boss` | boss manages x |
| Undirected (`↔`) | `… LINKED VIA "partner" WITH staff AS y` | mutual / either direction |

### Variants

| Pattern | Syntax |
|---------|--------|
| Two-node, outgoing | `FIND PATTERN IN staff AS x LINKED VIA "manages" TO staff AS y` |
| With `IN` keyword | `FIND PATTERN IN staff AS x LINKED VIA "manages" TO staff AS y` |
| Without `IN` keyword | `FIND PATTERN staff AS x LINKED VIA "manages" TO staff AS y` |
| Filter on alias | `FIND PATTERN staff AS x LINKED VIA "manages" TO staff AS y WHERE x.role = "lead"` |
| Three-node chain | `FIND PATTERN staff AS a LINKED VIA "manages" TO staff AS b LINKED VIA "mentors" TO staff AS c` |
| Incoming edge | `FIND PATTERN staff AS x LINKED VIA "manages" FROM staff AS boss` |
| Undirected edge | `FIND PATTERN staff AS x LINKED VIA "peer" WITH staff AS y` |
| Cross-bucket | `FIND PATTERN staff AS x LINKED VIA "lives_in" TO places AS p` |

```sql
-- Who does Ana manage that also mentors someone?
FIND PATTERN staff AS a LINKED VIA "manages" TO staff AS b LINKED VIA "mentors" TO staff AS c
-- Result: a=Ana → b=Ben → c=Dee

-- Cross-bucket: which staff live where?
FIND PATTERN staff AS s LINKED VIA "lives_in" TO places AS p
-- Result: s=Ana → p=Manila (or Cebu, depending on bonds)
```

---

## 14. DISTILL — aggregate a bucket

Run aggregation functions on a bucket's documents without returning individual records.

```sql
DISTILL FROM staff TOTAL age
```

| Aggregation | Syntax | Result key |
|-------------|--------|------------|
| Sum | `DISTILL FROM staff TOTAL age` | `total` |
| Sum (alias) | `DISTILL FROM staff SUM age` | `sum` |
| Average | `DISTILL FROM staff AVERAGE OF age` · `AVERAGE age` | `average` |
| Average (short) | `DISTILL FROM staff AVG age` | `avg` |
| Minimum | `DISTILL FROM staff MIN age` | `min` |
| Maximum | `DISTILL FROM staff MAX age` | `max` |
| Spread (max − min) | `DISTILL FROM staff SPREAD age` | `spread` |
| Count documents | `DISTILL FROM staff COUNT` · `DISTILL FROM staff TALLY` | `count` / `tally` |
| Count documents that have a field | `DISTILL FROM staff COUNT status` · `TALLY OF status` | `count` / `tally` |

- `COUNT` and `TALLY` are the same. With no field they count documents; with a field they count documents where that field is present (any type).
- All other aggregations use numeric values only.
- An unknown function returns `Unknown aggregation: BOGUS`.
- If no document matches (or the bucket doesn't exist) the result is `[]` with `count: 0`.

### AS — name the result

```sql
DISTILL FROM staff COUNT AS headcount
DISTILL FROM staff TOTAL age AS payroll_age
```

### Several aggregates at once (comma-separated)

```sql
DISTILL FROM staff TOTAL age AS total, MIN age AS youngest, MAX age AS oldest, COUNT AS n
```
Returns `{"total": 119.0, "youngest": 24, "oldest": 35, "n": 4}`.

### WHERE — aggregate only some documents

`WHERE` accepts the same conditions as `FIND` (`=`, `!=`, `>`, `<`, `>=`, `<=`, joined with `AND` / `OR`). It can go right after the bucket, after `GROUP BY`, or at the end.

```sql
DISTILL FROM staff WHERE dept = "Eng" TOTAL age
DISTILL FROM staff WHERE age > 25 COUNT
DISTILL FROM staff WHERE dept = "Eng" AND age > 30 COUNT
DISTILL FROM staff WHERE dept = "Eng" OR age < 5 TALLY AS n
DISTILL FROM staff COUNT WHERE status = "active"
```

### GROUP BY

Group results by a field, then aggregate within each group.

```sql
DISTILL FROM staff GROUP BY dept TOTAL age AS total_age
```

Returns:
```json
[
  {"dept": "Eng", "total_age": 63.0},
  {"dept": "Ops", "total_age": 56.0}
]
```

```sql
DISTILL FROM staff GROUP BY dept COUNT AS n
DISTILL FROM staff GROUP BY dept AVERAGE age
DISTILL FROM staff GROUP BY role TOTAL age AS total, AVERAGE age AS avg
DISTILL FROM staff GROUP BY dept WHERE age > 25 COUNT AS n
DISTILL FROM staff GROUP BY dept WHERE age > 30 TOTAL age AS t, COUNT AS n
DISTILL FROM staff GROUP BY dept TOTAL age AS t WHERE status = "active"
```

The bucket name may be quoted: `DISTILL FROM "staff" COUNT`.

---

## 15. HEAL — repair integrity

Clean up dangling bonds, broken document links (pointing to deleted/non-existent documents), and other stale data.

```sql
HEAL BONDS
HEAL LINKS
```

| Variant | Syntax | Effect |
|---------|--------|--------|
| Bonds only | `HEAL BONDS` | Removes bonds whose source or target document no longer exists |
| Links only | `HEAL LINKS` | Removes links whose source or target document no longer exists |
| Full repair | `HEAL ALL` | Heals bonds, links, and any other detectable inconsistencies |

Use `HEAL` after bulk deletes or when ghost relationships accumulate.

---

## 16. SUGGEST BONDS — find bonds you haven't made yet

Scans your documents and proposes bonds that are likely missing. It **only suggests** — nothing is created until you `BOND`.

```sql
SUGGEST BONDS
```

Example result:

```json
{"status": "ok", "count": 2, "suggestions": [
  {"source": "logs:l3", "target": "staff:c", "confidence": 0.95, "reason": "Field 'owner' references staff:c"},
  {"source": "logs:l1", "target": "staff:a", "confidence": 0.75, "reason": "Field 'user' matches the id of staff:a"}
]}
```

| Signal | Confidence | Example |
|--------|-----------|---------|
| A field holds a full document id | 0.95 | `{"owner": "staff:c"}` |
| A field holds the id of a document in another bucket | 0.75 | `{"user": "a"}` matches `staff:a` |
| Vector similarity in `_embeddings` | similarity score (> 0.5) | semantic closeness |

- Pairs that are already bonded (in either direction) are **not** suggested again.
- Suggestions are sorted by confidence; an empty list means nothing is missing.

```sql
SUGGEST BONDS                                          -- 1. see what's missing
BOND "logs:l1" TO "staff:a" AS "by"                    -- 2. accept a suggestion
SUGGEST BONDS                                          -- 3. it no longer appears
FIND "by" OF "logs:l1"                                 -- 4. use the new bond
```

All in one line: `SUGGEST BONDS BOND "logs:l1" TO "staff:b" AS "seen" SUGGEST BONDS`.

---

## 17. REWIND — restore a document to an earlier time

Puts a document back to the state it had at a given moment.

```sql
SHAPE BUCKET staff AUDITED        -- required once, BEFORE the changes you want to undo
CHANGE staff "a" SET age TO 36
CHANGE staff "a" SET age TO 37
REWIND "staff:a" TO "1 minutes ago"
```

| Variant | Syntax |
|---------|--------|
| Relative time | `REWIND "staff:a" TO "10 minutes ago"` · `"2 hours ago"` · `"yesterday"` |
| Absolute time | `REWIND "staff:a" TO "2026-10-05 14:30"` |
| Current state | `REWIND "staff:a" TO "now"` |
| Unix timestamp | `REWIND "staff:a" TO "1791191933"` |

Rules:
- The bucket must be `AUDITED` (or `VERSIONED`) **before** the changes happen — `REWIND` reads that history. Otherwise: `No history for 'staff:a'. Run SHAPE BUCKET staff AUDITED …`.
- The document id must be the full `bucket:id` form.
- If the document did not exist at that time you get `'staff:a' did not exist at that time.` and nothing changes.
- The rewind is itself logged, so you can `REWIND` again (e.g. to undo the rewind).
- Bonds are left untouched — they keep pointing at the document.

```sql
REWIND "staff:a" TO "1 minutes ago"
FIND staff "a"                                         -- shows the restored fields
FIND "pal" OF "staff:a"                                -- bonds still intact
```

---

## 18. INCINERATE — hard delete from the bin

`DRAIN` only moves a document to `_rubbish`. `INCINERATE` removes it from `_rubbish` **permanently**.

```sql
INCINERATE "a"             -- one drained document (plain id)
INCINERATE EVERYTHING      -- empty the whole bin
INCINERATE "a" FROM _rubbish   -- optional FROM _rubbish, same effect
```

- Only documents already in the bin are affected; a live document is never touched (`Incinerated 0 documents.`).
- There is no undo — `SALVAGE` and `RESTORE` find nothing afterwards.

```sql
DRAIN staff "a"
INCINERATE "a"            -- Incinerated 1 documents.
```

---

## 19. DROP — remove a whole bucket (recoverable)

Moves **every** document of a bucket to `_rubbish` and removes the bucket.

```sql
DROP pets
DROP BUCKET pets          -- BUCKET keyword is optional
DROP "pets"               -- quoted name also works
```

After the drop `SHOW buckets` no longer lists it and `FIND pets` returns 0 documents. Bonds are kept and work again after `RESTORE`.

---

## 20. RESTORE — bring a dropped bucket back

Takes every document of that bucket out of `_rubbish` and pours it back.

```sql
RESTORE pets
RESTORE BUCKET pets       -- BUCKET keyword is optional
```

- Also brings back documents that were individually `DRAIN`ed from that bucket.
- If the bin was emptied with `INCINERATE`, you get `Restored 0 documents`.
- For a single document use `SALVAGE "id"`; for the whole bin use `SALVAGE EVERYTHING`.

```sql
DROP pets
RESTORE pets
FIND pets
```

---

## 21. MIGRATE — reshape every document in a bucket

Rewrites documents that match a `FROM` pattern into a `TO` pattern. Capture values with `$1`, `$2`, … and reuse them on the right. It runs in the background without blocking, and each migrated document gets its `_version` raised.

```sql
MIGRATE users FROM {"fname":"$1"} TO {"first":"$1"}                    -- rename a field
MIGRATE users FROM {"lname":"$1"} TO {"last":"$1","surname":"$1"}      -- copy to two fields
MIGRATE users FROM {"first":"$1"} TO {"first":"$1","tag":"v2"}         -- add a field
MIGRATE "users" FROM {"fname":"$1"} TO {"first":"$1"}                  -- quoted bucket name
```

- Documents missing the `FROM` fields are left alone.
- Fields not mentioned in the pattern are untouched.
- Allow a moment to finish, then `FIND` the bucket to see the result.

---

## 22. AUTHENTICATE — set session user

Changes the current user context. This affects which security policies match, how rate limits apply, and the `tenant` field on webhooks and audit logs.

```sql
AUTHENTICATE AS "david"
AUTHENTICATE AS "users:david"
```

You can also use `SET` to place arbitrary variables into your session context for policies to read:
```sql
SET role = "viewer"
```

---

## 23. LIMIT — set rate quotas

Limits the number of CleaveQL queries a specific role can execute per minute. If a user exceeds it, the server returns a `429 Rate limit exceeded` error.

```sql
LIMIT 100 QUERIES PER MINUTE FOR "viewer"
LIMIT 5 QUERIES PER MINUTE FOR admin
LIMIT 0 QUERIES PER MINUTE FOR "guest"      -- blocks entirely
```

---

## 24. POLICY — memory limits and access rules

### Memory Management / Quota Policies
Defines what happens when a bucket hits its `MAX DOCUMENTS` limit (set via `SHAPE BUCKET`).

```sql
SHAPE BUCKET logs MAX DOCUMENTS 2
ENFORCE POLICY ON logs TO REPLACE LEAST RECENTLY USED    -- (default) evict oldest read
ENFORCE POLICY ON logs TO REPLACE OLDEST UPDATES         -- evict oldest write
ENFORCE POLICY ON logs TO OVERWRITE CURRENT              -- evict newest
```
Note: updating an existing document does not trigger an eviction.

### Document Security Level (DSL) Policies
Controls read and write access to documents. Context variables like `my role` or `@user_id` can be matched against document fields. If a `write` policy fails, the query errors. If a `read` policy fails, the document is simply hidden from `FIND`.

```sql
ENFORCE SECURITY POLICY "lvl" ON docs TO ALLOW read IF level < 3
ENFORCE SECURITY "own" ON docs TO ALLOW write IF owner = @user_id
ENFORCE SECURITY "adm" ON docs TO ALLOW all IF my role = "admin"
```
*Note: `SHAPE POLICY ...` is an alias for `ENFORCE SECURITY ...`.*

To remove a policy:
```sql
DROP SECURITY "lvl" ON docs
```

---

## 25. MASK — conditionally redact fields

Instead of blocking the whole document, `MASK` removes specific fields from the JSON returned by `FIND`.

```sql
MASK "secret" ON docs IF my role = "viewer"
MASK "salary" ON staff IF level > 3
```

To remove a mask:
```sql
DROP SECURITY "secret" ON docs
```

## 26. EVERY (CRON) — schedule repeating background tasks

Executes a command periodically in the background.

```sql
EVERY 5 SECONDS DO ( FIND docs )
EVERY 1 HOURS DO ( DISTILL FROM logs )
EVERY 30 MINUTES DO ( MIGRATE users FROM {"status":"old"} TO {"status":"stale"} )
```

---

## 27. ENRICH — add computed virtual fields

Automatically injects calculated fields into the documents returned by `FIND`.

```sql
ENRICH users WITH full_name AS CONCAT(first, " ", last)
ENRICH sales WITH tax AS price * 0.2
ENRICH items WITH margin AS price - cost, status AS "active"
```
Once enriched, the computed fields act as if they are stored in the document, and you can query or filter by them using `FIND`.

---

## 28. LISTEN — subscribe to real-time changes

Opens a live subscription that pushes events over the websocket whenever data changes in the target bucket or document.

```sql
LISTEN TO docs
LISTEN TO docs "1"
```

---

## 29. PEER — analyze queries and AI engine status

`PEER` is used for debugging and profiling query execution costs, acting similarly to `EXPLAIN` in SQL databases. It analyzes the nested statement and returns index suggestions without actually executing the query or modifying data.

```sql
PEER INTO COST ( FIND docs WHERE a = 1 )
```
You can also use it to peek at the status of the semantic vector engine:
```sql
PEER INTO ATTENTION
```

---

## 30. SET (CONTEXT) — inject session variables

Sets custom arbitrary variables in the active session context. These are evaluated in real-time by DSL Security Policies and Rate Limits.

```sql
SET role = "admin"
SET tenant_id = "acme_corp"
SET max_retries = 5
```

---

## 31. MATCH — Cypher-like advanced graph pattern traversal

While `FIND PATTERN` looks for a path starting from a single document, `MATCH` lets you search the entire graph for a specific shape using Cypher-like syntax (similar to Neo4j). You can assign aliases to nodes (`u` and `f`) and apply a `WHERE` clause across all resolved nodes.

```sql
MATCH (u FROM users)-["friend"]->(f FROM users)
MATCH (u FROM users)-["friend"]->(f FROM users) WHERE f.age > 20
```
This returns a list of matched subgraphs mapping each alias to the resolved document.

---

## 32. UNDO — View and revert global operation history

CleaveDB maintains a global timeline of all structural modifications (`POUR` and `CHANGE`). You can view this history and instantly roll back the database state to a specific point in time. 

When you undo a specific operation ID, CleaveDB recursively reverts **that operation and all subsequent operations** chronologically up to the present.

**Step 1: View History**
```sql
UNDO SHOW
```
*Returns an ordered list of changes. Each contains a `uid`, the `action`, and the `before` and `after` states.*

**Step 2: Revert to a specific state**
```sql
UNDO "tester.1791248457533_7852"
```
*Reverts the target operation and all newer modifications.*

---





## Combining the core commands

### FIND — mixing filters, sorting, limits and projection

```sql
FIND emp WHERE dept = "IT" AND age > 30 ARRANGED BY age GOING DOWN
FIND emp WHERE dept = "IT" YIELD name, age ARRANGED BY age GOING UP LIMIT 2
FIND emp WHOSE dept IS "HR" YIELD name
FIND emp MATCHING {"dept": "IT"} LIMIT 1
FIND emp MATCHING {"dept": "IT"} YIELD name
FIND emp "e1" YIELD name, age
SCOOP emp WHERE dept = "IT" ARRANGED BY age GOING DOWN LIMIT 1
```

Summaries accept a `WHERE` filter:

```sql
FIND THE FIRST 2 FROM emp WHERE dept = "IT"
FIND THE HIGHEST 1 age FROM emp WHERE dept = "IT"
FIND THE LOWEST 2 age FROM emp WHERE dept = "HR"
FIND THE TALLY OF emp WHERE dept = "IT"
```

### POUR + CHANGE + FIND — write, edit, read back

```sql
CHANGE emp "e1" SET age TO 36, dept TO "Ops"
FIND emp "e1"
FIND emp WHERE dept = "Ops"
```

### BOND — combining modifiers

```sql
BOND "emp:e1" TO "emp:e2" AS "mentor" WITH CONFIDENCE 0.9 EXPIRING IN 2 HOURS
FIND "mentor" OF "emp:e1"                      -- result carries "confidence": 0.9
BOND "emp:e1" AND "emp:e2" AS MUTUAL "peer" WITH AFFINITY 0.7
FIND "peer" OF "emp:e2"                        -- works from either side
BOND "emp:e1" TO ANY("emp:e2") AS "rep" EXCLUSIVELY
BOND "emp:e1" TO "emp:e2", "emp:e1" AS "many" WITH CONFIDENCE 0.5
```

### LINK + UNLINK — lightweight document & URL references

```sql
LINK "emp:e1" TO "emp:e2"
LINK "emp:e1" TO "https://company.org/directory/e1"
SHOW LINKS                                     -- lists all document & URL links
FIND LINKS OF "emp:e1"                         -- shows all links originating from e1
UNLINK "emp:e1" FROM "https://company.org/directory/e1" -- removes link
```

### BOND + CHANGE + FIND — conditional bonds follow the data

```sql
BOND "emp:e1" TO "emp:e2" AS "gate" IF role = "admin" ON DELETE CASCADE
FIND "gate" OF "emp:e1"                        -- e2.role is "admin": 1 result, status "active"
CHANGE emp "e2" SET role TO "user"
FIND "gate" OF "emp:e1"                        -- condition no longer true: 0 results
FIND CANDIDATE "gate" OF "emp:e1"              -- shown again, with status "candidate"
CHANGE emp "e2" SET role TO "admin"
FIND "gate" OF "emp:e1"                        -- active again
```

### DRAIN + SALVAGE + BOND — bonds travel with their documents

```sql
DRAIN emp WHERE dept = "HR" AND age > 26       -- drained doc's bonds disappear from FIND
FIND "mentor" OF "emp:e1"                      -- 0 results
SALVAGE "e2"                                   -- document back ...
FIND "mentor" OF "emp:e1"                      -- ... and so is the bond
```

### DRAIN + CASCADE — deleting propagates through bonds

```sql
BOND "staff:a" TO "staff:b" AS "backup" ON DELETE CASCADE
DRAIN staff "a"                                -- also drains staff:b (cascade)
FIND "backup" OF "staff:a"                     -- 0 results, both gone
```

### SEVER — one label, then everything

```sql
SEVER "emp:e1" FROM "emp:e2" AS "peer"         -- removes both directions of the mutual bond
SEVER "emp:e1" FROM "emp:e2"                   -- removes every remaining bond between them
```

### TRACE + FIND PATTERN — verify a chain with pattern matching

```sql
-- Set up a chain: bob →reports_to→ di →reports_to→ cy
BOND "staff:bob" TO "staff:di" AS "reports_to"
BOND "staff:di" TO "staff:cy" AS "reports_to"

-- Walk the chain
TRACE "reports_to" FROM "staff:bob"            -- returns [bob, di, cy]

-- Verify with pattern matching
FIND PATTERN staff AS a LINKED VIA "reports_to" TO staff AS b LINKED VIA "reports_to" TO staff AS c
-- Returns: a=bob, b=di, c=cy
```

### TRACE + mixed labels — cross-label traversal

```sql
BOND "staff:ana" TO "staff:bob" AS "manages"
BOND "staff:bob" TO "staff:dee" AS "mentors"

TRACE "manages", "mentors" FROM "staff:ana"    -- ana →manages→ bob →mentors→ dee
```

### FOLLOW + DIRECTION + DEPTH — full graph walk

```sql
-- Outgoing only
FOLLOW "staff:ana" THROUGH "manages" DIRECTION OUT      -- bob, cam

-- Incoming: who manages bob?
FOLLOW "staff:bob" THROUGH "manages" DIRECTION IN       -- ana

-- Both directions
FOLLOW "staff:ana" THROUGH "manages" DIRECTION BOTH     -- bob, cam

-- Multi-hop walk
FOLLOW "staff:bob" THROUGH "reports_to" DEPTH 2         -- cam, dee

-- Walk + sort + limit
FOLLOW "staff:ana" THROUGH "manages" ARRANGED BY age GOING DOWN LIMIT 2
```

### FOLLOW then DISTILL — explore then aggregate

```sql
FOLLOW "staff:ana" THROUGH "manages"                    -- see who's under Ana
DISTILL FROM staff GROUP BY dept TOTAL age AS total_age  -- aggregate the whole bucket
```

### FIND PATTERN cross-bucket — staff → places

```sql
BOND "staff:ana" TO "places:mnl" AS "lives_in"
FIND PATTERN staff AS s LINKED VIA "lives_in" TO places AS p
-- Returns: s=ana, p=Manila
```

### FIND PATTERN undirected — mutual bonds

```sql
BOND "staff:ana" AND "staff:eve" AS MUTUAL "peer"
FIND PATTERN staff AS x LINKED VIA "peer" WITH staff AS y
-- Returns paths from both sides
```

### FIND HOW — bond history (drift)

```sql
BOND "staff:ana" TO "staff:bob" AS "manages"
BOND "staff:ana" TO "staff:cam" AS "manages"

FIND HOW THE "manages" OF "staff:ana" CHANGED BETWEEN "yesterday" AND "tomorrow"
-- Returns: [{action: "BOND", target: "staff:bob"}, {action: "BOND", target: "staff:cam"}]

SEVER "staff:ana" FROM "staff:cam" AS "manages"

FIND HOW THE "manages" OF "staff:ana" CHANGED BETWEEN "2000-01-01" AND "2999-01-01"
-- Now includes: [{action: "BOND", …}, {action: "BOND", …}, {action: "SEVER", target: "staff:cam"}]
```

### Multi-command one-liner — POUR + BOND + FIND

```sql
POUR INTO staff "f" {"name":"Fay","role":"dev","dept":"Eng","age":22} BOND "staff:a" TO "staff:f" AS "manages" FIND "manages" OF "staff:a"
```

### SHOW + INDEX + GUARD + SHAPE together

```sql
GUARD staff WITH name IS REQUIRED, age >= 0
INDEX age ON staff
INDEX staff ON (dept, role)
SHAPE BUCKET staff AUDITED VERSIONED
SHOW INDEXES
SHOW STATS
DESCRIBE staff
```

---

### DISTILL + WHERE + GROUP BY — slice, then aggregate

```sql
DISTILL FROM staff WHERE status = "active" GROUP BY dept TOTAL age AS total, COUNT AS n
DISTILL FROM staff GROUP BY dept WHERE age > 30 TOTAL age AS t, COUNT AS n
DISTILL FROM staff COUNT WHERE dept = "Eng" OR age < 5
```

### DISTILL after changes — numbers follow the data

```sql
CHANGE staff "a" SET age TO 51
DISTILL FROM staff MAX age                     -- {"max": 51}
DRAIN staff "a"
DISTILL FROM staff COUNT                       -- drained documents are not counted
```

### SUGGEST BONDS + BOND + FOLLOW — discover, accept, explore

```sql
SUGGEST BONDS                                  -- logs:l1 → staff:a (field 'user' matches id 'a')
BOND "logs:l1" TO "staff:a" AS "by"
SUGGEST BONDS                                  -- that pair is gone from the list
FOLLOW "logs:l1" THROUGH "by"                  -- returns logs:l1 and staff:a
FIND "by" OF "logs:l1"
```

### REWIND + AUDITED/VERSIONED + DISTILL — undo and re-measure

```sql
SHAPE BUCKET staff VERSIONED
CHANGE staff "a" SET age TO 36
CHANGE staff "a" SET age TO 37
REWIND "staff:a" TO "1 seconds ago"            -- back to 36
FIND staff "a"
DISTILL FROM staff TOTAL age                   -- totals use the restored value
```

### REWIND + BOND — bonds survive a rewind

```sql
BOND "staff:a" TO "staff:b" AS "pal"
CHANGE staff "a" SET age TO 50
REWIND "staff:a" TO "now"
FIND "pal" OF "staff:a"                        -- bond still there
```

### One line — write, rewind, aggregate

```sql
CHANGE staff "a" SET age TO 51 REWIND "staff:a" TO "now" DISTILL FROM staff MAX age
```

### DRAIN + SALVAGE + INCINERATE — the recycle-bin lifecycle

```sql
POUR INTO staff "a" {"name":"Ana","age":35} POUR INTO staff "b" {"name":"Ben","age":28}
BOND "staff:a" TO "staff:b" AS "pal"
DRAIN staff "a" FIND staff FIND _rubbish SALVAGE "a" FIND staff FIND "pal" OF "staff:a"
DRAIN staff "b" INCINERATE "b" FIND _rubbish SALVAGE "b" FIND staff
```
`SALVAGE "b"` after `INCINERATE "b"` brings back 0 documents — incinerated means gone.

### DROP + RESTORE + DISTILL — drop a bucket, bring it back, same numbers

```sql
POUR INTO pets "p1" {"name":"Rex","age":3} POUR INTO pets "p2" {"name":"Tom","age":5}
DISTILL FROM pets TOTAL age DROP pets SHOW buckets RESTORE pets DISTILL FROM pets TOTAL age
```

### DRAIN + DROP + RESTORE — drained documents come back too

```sql
POUR INTO pets "p3" {"name":"Zed","age":7}
DRAIN pets "p3" DROP pets RESTORE pets FIND pets
```
`RESTORE` brings back every document of the bucket in the bin, including ones drained earlier.

### DROP + RESTORE + BOND — bonds survive a drop

```sql
BOND "pets:p1" TO "pets:p2" AS "pal" DROP pets RESTORE pets FIND "pal" OF "pets:p1"
```

### SHAPE AUDITED + DROP + RESTORE — edits are kept

```sql
SHAPE BUCKET pets AUDITED
CHANGE pets "p1" SET age TO 4
DROP pets RESTORE pets FIND pets "p1"           -- age is still 4
```

### DROP + INCINERATE — a bucket you can never get back

```sql
DROP pets INCINERATE EVERYTHING RESTORE pets SHOW buckets
```
`RESTORE` reports `Restored 0 documents`, and `SHOW buckets` does not list `pets`.

### MIGRATE + FIND + DISTILL — reshape, then query and aggregate

```sql
POUR INTO users "u1" {"fname":"Al","lname":"Bo","age":3}
MIGRATE users FROM {"fname":"$1"} TO {"first":"$1"}
FIND users                                      -- {"first":"Al","lname":"Bo","age":3,...}
DISTILL FROM users TOTAL age                    -- other fields are untouched
```

### MIGRATE twice — stack migrations

```sql
MIGRATE users FROM {"first":"$1"} TO {"first":"$1","tag":"v2"}
FIND users WHERE tag = "v2"
```

### MIGRATE + DRAIN + SALVAGE — migrated documents are what get recycled

```sql
DRAIN users "u1" FIND _rubbish SALVAGE "u1" FIND users
```

### AUTHENTICATE + ENFORCE SECURITY + FIND (Role-Based Access)
Restrict document access to specific tenants or roles.

```sql
AUTHENTICATE AS "users:alice"
SET role = "admin"

-- Only Alice can write to her own documents
ENFORCE SECURITY "own" ON docs TO ALLOW write IF owner_id = @user

-- Only admins can read this bucket
ENFORCE SECURITY "adm" ON docs TO ALLOW read IF my role = "admin"

FIND docs
```

### AUTHENTICATE + MASK + DISTILL (Redaction)
Masks apply to `FIND` to redact fields in the output JSON. However, `DISTILL` reads the raw document, bypassing the mask for aggregate stats.

```sql
AUTHENTICATE AS "guest"
SET role = "viewer"

-- Hide salary field from viewers in FIND results
MASK "salary" ON staff IF my role = "viewer"

FIND staff                               -- Salary is redacted
DISTILL FROM staff AVERAGE salary        -- Still returns the aggregate!
```

### SHAPE BUCKET + POLICY (Memory & Quotas)
Create a temporary bucket that automatically purges the oldest documents when it hits capacity.

```sql
SHAPE BUCKET temp_logs MAX DOCUMENTS 100
ENFORCE POLICY ON temp_logs TO REPLACE LEAST RECENTLY USED
POUR INTO temp_logs "1" {"event": "start"}
```

### AUTHENTICATE + LIMIT + FIND (Rate Limiting)
Prevent abuse by throttling queries for specific roles. Note that limits are enforced per-minute and checked during the websocket connection loop.

```sql
LIMIT 60 QUERIES PER MINUTE FOR "viewer"
LIMIT 1000 QUERIES PER MINUTE FOR "admin"
SET role = "viewer"

-- Over 60 queries in a minute will return a 429 Error
FIND docs
```
## Chaining commands

### A. Several commands in one line
Statements are executed in order and return one result each. No separator is needed. All commands can be mixed:

```sql
POUR INTO mix "m1" {"v": 1} POUR INTO mix "m2" {"v": 2} BOND "mix:m1" TO "mix:m2" AS "next" FIND "next" OF "mix:m1" CHANGE mix "m2" SET v TO 5 FIND mix WHERE v > 1 SEVER "mix:m1" FROM "mix:m2" AS "next" DRAIN mix "m2" FIND mix
```

```sql
POUR INTO chain "c3" {"v": 3} CHANGE chain "c3" SET v TO 99 FIND chain "c3" DRAIN chain "c3"
```

```sql
BOND "chain:c1" TO "chain:c2" AS "next" BOND "chain:c2" TO "chain:c1" AS "next" FIND "next" OF "chain:c1" SEVER "chain:c1" FROM "chain:c2" AS "next" FIND "next" OF "chain:c1"
```
The final `FIND` returns 0 documents — the bond is gone.

A write can be followed by a `PIPE` query in the same line:

```sql
POUR INTO emp "z1" {"name": "Zed", "age": 50, "dept": "IT"} PIPE FROM emp THEN WHERE age > 45 THEN SHOW name
```

### B. Transactions

```sql
BEGIN POUR INTO users "t1" {"name": "T1"} POUR INTO users "t2" {"name": "T2"} COMMIT
```

```sql
BEGIN POUR INTO mix "m3" {"v": 3} BOND "mix:m3" TO "mix:m1" AS "tx" CHANGE mix "m3" SET v TO 4 COMMIT
```

```sql
BEGIN POUR INTO users "t3" {"name": "T3"} ROLLBACK
```
After the `ROLLBACK`, `FIND users "t3"` returns 0 documents.

> **Limitation:** `ROLLBACK` only rolls back `POUR` / `POUR MANY` writes. `CHANGE`, `BOND`, `LINK`, `SEVER`, `UNLINK` and `DRAIN` run inside a transaction are **not** reverted. Use transactions for groups of `POUR`s.

### C. Multi-hop bond chains
Follow bonds across several hops in one `FIND`:

```sql
BOND "users:jane" TO "users:juan" AS "boss"
BOND "users:juan" TO "users:pedro" AS "knows"
FIND THE knows OF THE boss OF users "jane"      -- returns users:pedro
```

### D. PIPE — chain processing stages on a bucket
`PIPE FROM <bucket>` followed by `THEN` stages, each feeding the next.

| Stage | Syntax |
|-------|--------|
| Filter | `THEN WHERE age > 20` |
| Sort | `THEN ARRANGED BY age GOING DOWN` (or `UP`) |
| Limit | `THEN LIMIT 3` |
| Project | `THEN SHOW name, age` |
| Group + aggregate | `THEN GROUP BY city TALLY AS n` |
| Aggregates | `TOTAL OF age AS total_age`, `AVERAGE OF age AS avg_age`, `MIN OF age AS youngest`, `MAX OF age AS oldest` (also `SPREAD`) |

```sql
PIPE FROM users THEN WHERE age > 20 THEN ARRANGED BY age GOING DOWN THEN LIMIT 3 THEN SHOW name, age
```

```sql
PIPE FROM emp THEN WHERE dept = "IT" THEN ARRANGED BY age GOING UP THEN SHOW name
```

```sql
PIPE FROM emp THEN GROUP BY dept TALLY AS n, MIN OF age AS youngest, MAX OF age AS oldest, AVERAGE OF age AS avg
```

### EVERY + DISTILL (Scheduled Reporting)
Periodically calculate aggregates and store the result or trigger a webhook.

```sql
EVERY 1 HOURS DO ( DISTILL FROM sales TOTAL price )
EVERY 1 DAYS DO ( DRAIN temp_logs FIND _rubbish )
```

### ENRICH + FIND + MASK (Virtual Redaction)
You can compute a virtual field and then apply security masks or filters to it.

```sql
ENRICH users WITH is_adult AS age >= 18
MASK "is_adult" ON users IF my role = "guest"
FIND users WHERE is_adult = true
```

### LISTEN + POUR + ENRICH (Live Computed Feeds)
Open a subscription to a bucket that has computed fields. As new documents are `POUR`ed in, the `LISTEN` stream will automatically push the document *including* the virtual enriched fields to your connected clients.

```sql
ENRICH sensors WITH fahrenheit AS (celsius * 9/5) + 32
LISTEN TO sensors
-- (In another session) POUR INTO sensors "s1" {"celsius": 20}
-- (The listener will receive {"celsius": 20, "fahrenheit": 68})
```

### SET + LIMIT + ENFORCE SECURITY (Testing Security Rules)
Dynamically mock the execution environment to test user policies or quotas.

```sql
AUTHENTICATE AS "cron"
SET role = "admin"
SET location = "US"

-- Because context variables were set, this will pass
ENFORCE SECURITY "loc" ON docs TO ALLOW write IF region = @location
LIMIT 5 QUERIES PER MINUTE FOR "admin"
```

### PEER + INDEX + FIND (Performance Tuning)
When querying a large bucket, use `PEER INTO COST` first to check if the query does a full table scan. After creating the index, run `PEER` again to verify it is using the index, then run the query.

```sql
-- Step 1: Check the cost. If it returns "scan_type": "FULL_BUCKET_SCAN", it's slow.
PEER INTO COST ( FIND logs WHERE level = "error" )

-- Step 2: Create the recommended index.
INDEX logs ON (level)

-- Step 3: Check again. Now it returns "scan_type": "INDEX_SCAN".
PEER INTO COST ( FIND logs WHERE level = "error" )

-- Step 4: Run the actual query quickly.
FIND logs WHERE level = "error"
```

### BOND + MATCH (Multi-hop Graph Queries)
Connect distinct documents with semantic edge labels and then query deeply across the entire graph. You can enforce conditions across any node in the path.

```sql
BOND "users:1" TO "users:2" AS "friend"
BOND "users:2" TO "docs:42" AS "owns"

-- Find the documents owned by a friend of a specific user
MATCH (u FROM users)-["friend"]->(f FROM users)-["owns"]->(d FROM docs) WHERE u.name = "Alice"
```

### UNDO + SHOW (Global Rollback)
Instead of relying on transactions, you can make permanent writes, audit them via the global `UNDO SHOW` stack, and dynamically roll back mistakes.

```sql
POUR INTO products "1" {"price": 100}
CHANGE products "1" SET price TO 9999    -- Accidental bad price update

-- Check the undo stack
UNDO SHOW

-- Roll back to the original POUR operation, reverting the CHANGE automatically
UNDO "tester.1791248457533_7852"
```
