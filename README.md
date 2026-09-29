<div align="center">
  <h1>🧬 CleaveDB 3.0</h1>
  <p><strong>The polyglot, AVX-512 accelerated, non-relational database with Transformer attention layers.</strong></p>
  
  [![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
  [![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)]()
  [![Rust](https://img.shields.io/badge/Rust-2021-orange.svg)]()
  [![License](https://img.shields.io/badge/license-MIT-green.svg)]()
</div>

<br/>

**CleaveDB 3.0** is a ground-up, hybrid NoSQL document database that eliminates the complexity of traditional SQL `JOIN`s, external vector search services, and opaque graph databases. It ships with:

- A high-performance **Rust storage engine** built entirely from scratch — no SQLite, no RocksDB, no external storage libraries.
- **AVX-512 / AVX2 C++ SIMD extensions** wired directly into the Rust engine for hardware-accelerated math operations.
- A **Python interpreter frontend** (via PyO3 bindings) that runs the **CleaveQL** query language.
- **Real neural Transformer embeddings** for semantic search via a quantized ONNX model, using ~22MB of RAM.
- A **TCP server** (`cleavedb_server.py`) with a full authentication shell, background Cron worker, and live query execution.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  CleaveQL (Python Layer)                │
│   Lexer ──► Parser ──► AST ──► Interpreter             │
│         attention/sra.py  ─── ONNX Q8 Transformer      │
│         cleaveql/security.py ── Row Level Security      │
│         cleaveql/cost_model.py ── Query Cost Estimation │
└────────────────────────┬────────────────────────────────┘
                         │  PyO3 FFI
┌────────────────────────▼────────────────────────────────┐
│              Rust Storage Engine                        │
│   BPlusTree ── WAL (Group Commit) ── Buffer Pool        │
│   Bloom Filter ── LZ4 Page Compression ── AES-256-GCM  │
│   SIMD FFI: AVX-512 dot_product, softmax, gelu, matmul │
└─────────────────────────────────────────────────────────┘
```

### Storage Engine Internals (Rust)
The Rust engine is built from the following hand-crafted components:

| Module | Description |
|---|---|
| `page` | 16KB fixed-size pages with CRC32 checksums |
| `buffer_pool` | CLOCK-sweep page cache with pin/unpin semantics |
| `wal` | Write-ahead log with group commit (lock-free `SegQueue`) |
| `btree` | Persistent B+Tree for documents, indexes, and bond edges |
| `bloom` | Bloom filter for fast key existence checks |
| `crypto` | AES-256-GCM encryption for fields at rest (via `sha2` + `aes-gcm`) |
| `simd_ffi` | FFI bindings to C++ AVX-512/AVX2 routines (dot product, matmul, softmax, gelu, layer norm, sigmoid) |

### Transformer Attention Layers (Python / `attention/`)

| Module | Description |
|---|---|
| `attention/sra.py` | **Semantic Relevance Attention** — Real ONNX Q8_0 embedding model for `MEANING` queries |
| `attention/__init__.py` | Manages the four planned attention layers: QUA, SRA, BDA, AQP |

---

## 🚀 Getting Started

### Requirements
- Python 3.13+
- Rust 2021 Edition (`cargo`)
- C++ build tools (for SIMD extensions)
- `onnxruntime`, `tokenizers`, `huggingface_hub`, `numpy`

### Installation
```bash
# 1. Build the Rust storage engine
cd storage
maturin develop --release

# 2. Install Python dependencies
pip install onnxruntime tokenizers huggingface_hub numpy

# 3. Start the TCP server
python cleavedb_server.py

# 4. Or use the CLI directly
python cleave_cli.py
```

### Connecting
The server runs on `localhost:5001` (TCP). The CLI handles the connection automatically.

---

## 🔒 Authentication Shell

Before any query can be executed, every client must authenticate. The server enforces a full credential system backed by the Rust B+Tree.

### First-Time Registration
Only **one account** can ever be registered. After that, registration is permanently locked. The first account is always granted the `admin` role.

```json
{ "action": "register", "username": "alice", "password": "MyStr0ng!", "dev_password": "DevPass!", "question": "What is your dog's name?", "answer": "rover" }
```

### Login
```json
{ "action": "login", "username": "alice", "password": "MyStr0ng!" }
```

### Password Recovery (2-Step)
**Step 1:** Retrieve your encrypted security question from the database:
```json
{ "action": "forgot_step1", "username": "alice" }
```
**Step 2:** Submit your answer and set a new password:
```json
{ "action": "forgot_step2", "username": "alice", "answer": "rover", "new_password": "NewStr0ng!" }
```

> **How it works:** Passwords are hashed with a random salt using SHA-256. Security questions and answers are encrypted at rest using the database's AES-256-GCM cipher before being stored in the hidden `_auth` bucket inside the B+Tree.

---

## 📖 The CleaveQL Language

CleaveQL is designed to read like a human conversation, not like machine code. Every query maps to a concrete AST node which is executed directly by the Python interpreter against the Rust engine.

---

### POUR — Insert / Upsert Documents

`POUR` is the primary write verb. It inserts or fully replaces a document in a bucket (collection).

**Using a Specific ID:**
When you know exactly what you want the document's key to be, provide it as a quoted string. CleaveDB will always upsert — if the ID already exists, it will overwrite it completely.
```sql
POUR INTO users "alice" {"name": "Alice", "age": 28, "role": "admin"}
POUR INTO products "prod-001" {"name": "Laptop", "price": 999}
```

**Using a Random / Auto-Generated ID:**
When you don't care what the ID is (e.g., ingesting a stream of events), use `RANDOM`. CleaveDB generates a cryptographically random 64-bit hex ID guaranteed to be unique.
```sql
POUR INTO events RANDOM {"type": "click", "page": "/home"}
-- Result gid: "events:406312a2755e5c92"

POUR INTO products RANDOM {"name": "Thick Wool Coat", "price": 79}
-- Result gid: "products:8823f15f25735fa7"
```

**Bulk Insert (POUR MANY):**
Insert multiple documents in a single statement:
```sql
POUR MANY INTO users [
  {"name": "Bob"},
  {"name": "Charlie"},
  {"name": "Diana"}
]
```

---

### SCOOP — Query / Retrieve Documents

`SCOOP` is the primary read verb. Every query variation begins with `SCOOP`.

**Retrieve Everything:**
```sql
SCOOP EVERYTHING FROM users
```

**Filter with WHOSE:**
Filter documents by a field value using the easy English `WHOSE ... IS ...` clause.
```sql
SCOOP EVERYTHING FROM users WHOSE role IS "admin"
SCOOP EVERYTHING FROM products WHOSE category IS "electronics"
```

**Full-Text Search with MENTIONING:**
Find documents where any field contains a specific substring anywhere in its body.
```sql
SCOOP EVERYTHING FROM articles MENTIONING "quantum computing"
```

**Retrieve a Specific Document:**
```sql
SCOOP users "alice"
```

**Limit Results:**
```sql
SCOOP EVERYTHING FROM users LIMIT 10
```

---

### CHANGE — Partial Update

`CHANGE` performs a **partial update** (patch) on an existing document. It modifies only the specified field and leaves all other fields untouched.

**Update a Single Field:**
```sql
CHANGE users "alice" SET age TO 29
CHANGE products "prod-001" SET price TO 1099
```

**Set a Field to a JSON Object:**
```sql
CHANGE users "alice" SET address TO {"city": "New York", "zip": "10001"}
```

---

### DRAIN — Delete Documents

`DRAIN` removes a document from the database.

**Delete a Single Document:**
```sql
DRAIN FROM users "alice"
```

---

## ✨ Feature Deep Dives

---

### Feature 1: Hardware-Efficient AI Semantic Search (`MEANING`)

Most databases require you to set up a completely separate vector search service (like Pinecone or Weaviate) alongside your main database. CleaveDB eliminates this entirely.

**How it works:**
1. When the server starts, `attention/sra.py` (Semantic Relevance Attention) automatically downloads and caches the `all-MiniLM-L6-v2` model from HuggingFace (~22MB).
2. The model is in ONNX quantized (Q8_0) format, executed by the `onnxruntime` `CPUExecutionProvider`.
3. On AVX-512/AVX2 capable CPUs, `onnxruntime` transparently uses hardware SIMD vector instructions for the tensor math, the same way the Rust engine's `simd_ffi` module does.
4. When a `MEANING` query arrives, the engine embeds the search phrase **once** (< 5ms), then computes the cosine similarity against document text content.
5. Every returned document receives an `_embedding_distance` score from `0.0` to `1.0` indicating how semantically similar it is to the query. Results are automatically sorted highest-to-lowest.

**Usage:**
```sql
-- Insert products
POUR INTO products RANDOM {"name": "Thick Wool Coat", "category": "Clothing"}
POUR INTO products RANDOM {"name": "Summer Beach Towel", "category": "Accessories"}
POUR INTO products RANDOM {"name": "Hiking Boots", "category": "Footwear"}

-- Semantic search — no keywords, no schema, just meaning
SCOOP EVERYTHING FROM products MEANING "something warm for cold weather"
```

**Live Result:**
```json
{
  "documents": [
    { "gid": "products:8823...", "body": { "name": "Thick Wool Coat" }, "_embedding_distance": 0.375 },
    { "gid": "products:fe28...", "body": { "name": "Summer Beach Towel" }, "_embedding_distance": 0.339 }
  ],
  "count": 2
}
```
The Wool Coat correctly scores **higher** than the Beach Towel because the Transformer model understands the semantic relationship between "Coat", "Wool", and "cold weather" — without any explicit keyword overlap.

---

### Feature 2: Self-Documenting Engine (`DESCRIBE`)

You never need to leave your terminal to look up documentation. CleaveDB can describe itself.

**Profile a Bucket (Pandas-style):**
Instantly compute statistics about any bucket — document count, field coverage, data types.
```sql
DESCRIBE users
-- Result: "Bucket 'users' (4 docs). Stats computed successfully."
```

**Read the Built-in Tutorials:**
Ask the database to explain any keyword or feature to you.
```sql
DESCRIBE MEANING
-- Result: "TUTORIAL: Semantic Search (MEANING)\nUse SCOOP EVERYTHING FROM bucket MEANING text"
```

---

### Feature 3: Nested Pipelines — Sub-Scoops & Sub-Pours

SQL sub-queries are notoriously hard to read. CleaveDB uses parenthesized sub-scoops that evaluate inner-first, and the result of the inner query is directly injected into the outer statement's target field.

**Dynamically Build a Nested Array from another Bucket:**
The following query finds every user whose `role` is `"developer"` and injects the entire list directly into the `new_hires` field of the `devs` team — in a single atomic statement.
```sql
CHANGE teams "devs" SET new_hires TO (SCOOP EVERYTHING FROM users WHOSE role IS "developer")
```

The `teams:devs` document now looks like:
```json
{
  "team_name": "Engineers",
  "new_hires": [
    { "gid": "users:u2", "body": { "age": 65, "role": "developer" } }
  ]
}
```

**Pour into a Nested Field Deep Inside an Existing Document:**
```sql
POUR {"tool": "CleaveDB"} INSIDE users "alice" AT path.to.skills
```

---

### Feature 4: Time-Travel Queries — MVCC (`AS OF YESTERDAY`)

Every time a document is modified, CleaveDB shadows a copy of the previous state into a hidden bucket named `_history_<bucket>`. This gives you a native MVCC (Multi-Version Concurrency Control) ledger. You can rewind the database and query it as it existed in the past.

**Workflow:**
```sql
-- Original state: Alice is 28
POUR INTO users "alice" {"name": "Alice", "age": 28}

-- Some time later, update the record
CHANGE users "alice" SET age TO 99

-- Now travel back to see the historical snapshot
SCOOP EVERYTHING FROM users AS OF YESTERDAY
```

The time-travel query reads from `_history_users` and returns the documents as they existed before the most recent changes.

---

### Feature 5: Deep Graph Traversal (Easy English)

NoSQL databases typically require your application code to manually loop over related documents across multiple queries. CleaveDB resolves entire relationship chains natively in a single query.

**Step 1: Bond Your Documents:**
```sql
POUR INTO users "alice" {"name": "Alice"}
POUR INTO users "bob" {"name": "Bob"}
POUR INTO users "charlie" {"name": "Charlie"}

-- Alice is friends with Bob
BOND "users:alice" TO "users:bob" AS "friend"
-- Bob is friends with Charlie  
BOND "users:bob" TO "users:charlie" AS "friend"
```

**Step 2: Traverse at Depth 1 (Direct Friends):**
```sql
SCOOP THE friend OF users "alice"
-- Returns: Bob
```

**Step 3: Traverse at Depth 2 (Friends of Friends):**
Simply chain the English naturally. The engine recursively evaluates each hop.
```sql
SCOOP THE friend OF THE friend OF users "alice"
-- Returns: Charlie (and Alice, because the MUTUAL bond makes Bob→Alice reciprocal)
```

**You can chain as deep as your graph needs:**
```sql
SCOOP THE manages OF THE manages OF THE manages OF org "ceo"
```

**Retrieve All Bonds by Label (Legacy syntax still supported):**
```sql
SCOOP RELATED "friend" FROM "users:alice"
```

---

### Feature 6: 15-Dimensional Graph Bonds

A `BOND` in CleaveDB is not just a static pointer. It is a richly configurable relationship object with up to 15 behavioral dimensions enforced natively by the engine.

**Basic Labeled Bond:**
```sql
BOND "users:alice" TO "users:bob" AS "friend"
```

**Mutual / Bidirectional Bond:**
Traversal works in **both** directions automatically.
```sql
BOND "users:alice" TO "users:bob" AS MUTUAL "friend"
```

**Time-Bound / Ephemeral Bond:**
The bond automatically expires and is no longer traversable after the time elapses.
```sql
BOND "users:alice" TO "session:s1" AS "active_session" EXPIRING IN 1 HOUR
BOND "users:alice" TO "promo:summer" AS "eligible" EXPIRING IN 30 DAYS
```

**Cascading Constraint:**
When the source document is deleted, the engine will automatically cascade and remove all linked targets.
```sql
BOND "order:5521" TO "users:alice" ON DELETE CASCADE
```

**Probabilistic Bond:**
Attach a confidence or affinity score to the relationship. Useful for recommendation engines and knowledge graphs.
```sql
BOND "document:1" TO "topic:ai"      AS "tagged"     WITH CONFIDENCE 0.94
BOND "users:bob"  TO "product:shoes" AS "interested" WITH AFFINITY 0.87
```

**All bond metadata is stored inside the hidden `_bonds` bucket in the B+Tree**, making the full relationship graph queryable and inspectable at any time.

---

### Feature 7: Conversational Analytics

CleaveDB translates human-readable aggregation phrases directly into internal map-reduce pipelines — no SQL `GROUP BY`, `COUNT(*)`, or `SUM()` required.

**Count Total Documents in a Bucket (TALLY):**
```sql
SCOOP THE TALLY OF users
-- Returns: { "mode": "TALLY", "count": 4, "documents": [...all docs...] }
```

**Get Distinct Values for a Field (UNIQUE):**
Equivalent to SQL `SELECT DISTINCT`. Returns only one representative document per unique value.
```sql
SCOOP ONLY UNIQUE department FROM employees
-- Returns: Engineering, Sales (deduplicated)
```

**Sum a Numeric Field Grouped by Another Field (TOTAL ... GROUPED BY):**
Equivalent to SQL `SELECT department, SUM(salary) GROUP BY department`.
```sql
SCOOP THE TOTAL salary FROM employees GROUPED BY department
-- Returns:
-- { "department": "Engineering", "salary": 80000 }
-- { "department": "Sales",       "salary": 110000 }
```

**Retrieve the Top N Documents by a Field (HIGHEST):**
```sql
SCOOP THE HIGHEST 5 salary FROM employees
-- Returns top 5 employees sorted by salary descending
```

**Retrieve the Bottom N Documents by a Field (LOWEST):**
```sql
SCOOP THE LOWEST 3 score FROM leaderboards
-- Returns bottom 3 entries sorted by score ascending
```

---

### Feature 8: Easy English Sorting

Forget `ORDER BY field ASC/DESC`. CleaveDB uses the most natural way to express order.

**Ascending (Lowest First):**
```sql
SCOOP EVERYTHING FROM leaderboards ARRANGED BY score GOING UP
-- Bob(12) → John(45) → Alice(88)
```

**Descending (Highest First):**
```sql
SCOOP EVERYTHING FROM leaderboards ARRANGED BY score GOING DOWN
-- Alice(88) → John(45) → Bob(12)
```

Sorting can be combined with filtering:
```sql
SCOOP EVERYTHING FROM employees WHOSE department IS "Sales" ARRANGED BY salary GOING DOWN
```

---

### Feature 9: Native Background Cron Workers (`EVERY ... DO`)

CleaveDB eliminates the need for external job schedulers (like `cron`, Celery, or Airflow) for database-level recurring tasks. Scheduled tasks are saved directly into the hidden `_cron` bucket inside the B+Tree and executed by a real `asyncio` background coroutine running inside `cleavedb_server.py`.

**Schedule a Recurring Task:**
```sql
-- Run a count every 5 seconds
EVERY 5 SECONDS DO (SCOOP THE TALLY OF users)

-- Hourly data maintenance
EVERY 1 HOUR DO (SCOOP EVERYTHING FROM sessions WHOSE expired IS true)
```

**How it works:**
1. The statement saves a job record to `_cron` with an `interval`, `last_run`, and `command` string.
2. The `cron_worker()` coroutine inside `cleavedb_server.py` wakes up every second.
3. It scans `_cron`, calculates `current_time - last_run >= interval`, and if true, parses and executes the stored CleaveQL command through the full Lexer → Parser → Interpreter pipeline as the `admin` user.
4. `last_run` is updated immediately before execution to prevent duplicate runs.

Each job is assigned a unique `job_id` returned in the response:
```json
{
  "status": "ok",
  "message": "Scheduled task added to background worker. Will execute every 5 seconds.",
  "job_id": "2b04d1d2"
}
```

---

### Feature 10: Row Level Security & Field Masking

CleaveDB has a native policy engine (`cleaveql/security.py`) that enforces row-level access control and field-level data masking directly inside the interpreter — before any data is returned to the client.

**Set the Current User Context:**
```sql
SET CONTEXT user = "alice"
SET CONTEXT role = "admin"
```

**Declare a Row-Level Security Policy:**
A policy evaluates a condition against each document and the current context. Only documents where the condition is `true` are returned.
```sql
-- Users can only see their own data
POLICY ON users FOR READ WHERE owner == @user
```

**Declare a Field Mask:**
Redact a sensitive field from any user who doesn't match a condition.
```sql
-- Mask the salary field for all non-admin users
MASK salary ON employees WHERE @role != "admin"
```
A masked field is returned as `"***MASKED***"` — the data is never sent over the wire to unauthorized clients.

---

### Feature 11: SHOW & HEAL (Index Management)

**Show Bucket Metadata:**
```sql
SHOW users
-- Returns bucket statistics from the B+Tree engine
```

**Declare an Index:**
```sql
INDEX users ON role
```

**Repair / Rebuild an Index:**
```sql
HEAL users
-- Triggers the engine's heal() method to rebuild corrupted or stale indexes
```

---

## 🔧 TCP Server Reference

The server is started with:
```bash
python cleavedb_server.py
```

It runs on `localhost:5001` by default. Every client connection goes through the following lifecycle:

1. **Authentication Phase:** The client must send a `register` or `login` JSON action. The server will not process any queries until the client is authenticated.
2. **Query Phase:** After successful login, the client sends raw CleaveQL query strings (one per line). Each query is parsed, planned, and executed. The result is returned as a JSON array.
3. **Disconnection:** When the TCP stream closes, the session ends. The Cron Worker continues running independently in the background.

### Wire Protocol
All messages are newline-delimited JSON (`\n`).

**Request:** A raw CleaveQL string, e.g.:
```
SCOOP EVERYTHING FROM users\n
```

**Response:** A JSON array:
```json
[{"status": "ok", "mode": "EVERYTHING", "documents": [...], "count": 4}]
```

---

## 📂 Project Structure

```
dsc/
├── storage/                  # Rust storage engine (maturin)
│   └── src/
│       ├── lib.rs            # Module root & public exports
│       ├── page.rs           # 16KB page with CRC32 checksum
│       ├── buffer_pool.rs    # CLOCK-sweep page cache
│       ├── wal.rs            # Write-ahead log, group commit
│       ├── btree/            # Persistent B+Tree
│       ├── bloom.rs          # Bloom filter
│       ├── crypto.rs         # AES-256-GCM at-rest encryption
│       ├── simd_ffi.rs       # AVX-512/AVX2 C++ FFI bindings
│       └── python.rs         # PyO3 Python bindings
│
├── cleaveql/                 # Python query language frontend
│   ├── lexer.py              # Tokenizer
│   ├── tokens.py             # Token type enum
│   ├── parser.py             # Recursive descent parser → AST
│   ├── ast.py                # AST node definitions
│   ├── interpreter.py        # AST executor against Rust engine
│   ├── security.py           # Row-level security & field masking
│   └── repl.py               # Interactive REPL
│
├── attention/                # AI Transformer attention modules
│   ├── sra.py                # Semantic Relevance Attention (ONNX Q8_0)
│   └── __init__.py
│
├── cleavedb_server.py        # TCP server, auth shell, cron worker
├── cleave_cli.py             # Command-line client
└── build.py                  # Build script
```
