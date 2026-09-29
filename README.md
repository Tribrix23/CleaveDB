<div align="center">
  <h1>🗡️ CleaveDB 3.0</h1>
  <p><strong>The polyglot, AVX-512 accelerated, non-relational database with Transformer attention layers.</strong></p>
  
  [![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
  [![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)]()
  [![Rust](https://img.shields.io/badge/Rust-2021-orange.svg)]()
  [![License](https://img.shields.io/badge/license-MIT-green.svg)]()
</div>

<br/>

**CleaveDB 3.0** is an experimental, hybrid NoSQL database built for extreme performance and expressive relationship traversal. It bridges the gap between document flexibility and graph connectivity. The engine is written in **Rust** (with C++ AVX-512 extensions) for zero-cost abstractions, bounded by a **Python** frontend (PyO3) that powers the heavily optimized **Conversational CleaveQL** query language, with a **Go** coordinator for distributed scatter-gather routing.

---

## 🧠 Core Architecture & Internals

Unlike traditional databases, CleaveDB is built from the ground up to support modern AI, semantic search, and complex graph traversal without compromising on raw ACID transactional speed.

### The Storage Engine (Rust)
- **B+Tree Sharding:** Data is organized in 16KB slotted pages for optimal NVMe disk alignment. 
- **CLOCK-Sweep Buffer Pool:** A highly concurrent memory manager ensures hot pages stay in memory while background threads flush dirty pages to disk.
- **Asynchronous WAL:** Write-Ahead Logging guarantees durability without blocking the main execution threads.
- **SIMD Neural Engine:** Hardware-accelerated term extraction (AVX-512) and native multi-head attention capabilities allow for lightning-fast inverted indexing and semantic routing.

### The Query Engine (Python / CleaveQL)
- **Volcano Execution Model:** Queries are parsed into an AST and executed via a streaming Volcano model.
- **Cost-Based Optimizer:** Automatically rewrites queries to push down predicates and collapse bond traversals.
- **Polyglot PyO3 Bridge:** The Python frontend talks directly to the Rust memory space, bypassing expensive serialization overheads.

```mermaid
flowchart TD
    subgraph Frontend [Python Frontend]
        REPL[CleaveQL REPL] --> Lexer
        Lexer --> Parser
        Parser --> AST
        AST --> Optimizer[Query Optimizer]
        Optimizer --> Interpreter[Volcano Executor]
    end

    subgraph Backend [Rust Storage Engine]
        Interpreter -- "PyO3 FFI" --> Core[CleaveDB Core]
        Core --> Index[Inverted Index / SIMD]
        Core --> Shards[B+Tree Shard Manager]
        Shards --> BP[Buffer Pool]
        BP --> WAL[Write-Ahead Log]
        BP --> Disk[(Disk IO)]
    end
```

---

## 📚 Complete Tutorial: How to Use CleaveDB

Welcome to the CleaveDB ecosystem! This tutorial will take you from booting the engine to building complex, secured graph queries.

### Step 1: Starting the Database
Once you have built the native extensions (via `python build.py`), you can start the interactive shell:
```bash
python cleavedb.py
```
You are now inside the CleaveQL REPL. CleaveQL is a declarative, case-insensitive, English-like query language. 

### Step 2: Basic Data Ingestion (POUR)
Data is stored in logical containers called **Buckets** (similar to tables). Let's insert some user data using the `POUR` command.

```sql
-- Insert a single document
POUR INTO users "u1" {"name": "Alice", "role": "admin", "department": "engineering"}

-- Insert multiple documents at once
POUR MANY INTO users [
  {"name": "Bob", "role": "developer", "department": "engineering"},
  {"name": "Charlie", "role": "sales", "department": "business"}
]
```
*Note: CleaveDB is schema-less. You can insert any valid JSON structure into a bucket.*

### Step 3: Conversational Extractions (SCOOP)
CleaveDB is fundamentally a non-SQL database. We do not use legacy SELECT, WHERE, or JOIN statements. Instead, CleaveQL uses a **Conversational Data Language** designed to read exactly like plain English.

Data is extracted using the SCOOP command, paired with **Command Modes** and **Fluent Predicates**:

`sql
-- 1. Extract everything from a bucket
SCOOP EVERYTHING FROM users

-- 2. Extract only unique fields (The engine hashes and drops duplicates)
SCOOP ONLY UNIQUE city FROM users

-- 3. Extract a limited slice natively from the B+Tree
SCOOP THE FIRST 5 FROM orders

-- 4. Fluent Predicates (No math symbols like '=', '>', '<')
SCOOP EVERYTHING FROM users WHOSE role IS "dev"

-- 5. Field Projections (Yielding specific keys and dropping the rest)
SCOOP THE FIRST 10 FROM users WHOSE city IS "Seattle" YIELD name, email
`
This syntax allows you to express complex extraction logic naturally without breaking mental flow.
### Step 4: Modifying & Deleting Data
Partial updates and deletions are extremely fast thanks to the B+Tree backend.

```sql
-- Update Bob's role
CHANGE users "u2" SET role TO "lead_developer"

-- Delete Charlie's record completely
DRAIN users "u3"
```

### Step 5: Graph Relationships (BONDS & FOLLOW)
Unlike relational databases that require slow `JOIN` operations, CleaveDB uses **Bonds** to create strict, native graph edges between documents.

Let's insert some orders and bind them to our users:
```sql
POUR MANY INTO orders [
  {"id": "ord_1", "user_id": "u1", "item": "Laptop"},
  {"id": "ord_2", "user_id": "u2", "item": "Monitor"}
]

-- Declare a relationship from Users to Orders
BOND user_orders FROM users.id TO orders.user_id STRICT
```

Now, instead of joining, we traverse the graph using `FOLLOW`:
```sql
-- Find everything connected to Alice (u1) up to 3 hops away!
FOLLOW "u1" THROUGH user_orders DIRECTION OUT DEPTH 3
```

### Step 6: Document-Level Security (DLS)

**Definition:** Document-Level Security (DLS) is CleaveDB's native policy engine. Because CleaveDB is a non-relational database, traditional Row-Level Security (RLS) terminology does not apply. Instead, DLS allows you to define declarative logic gates (`SHAPE POLICY`) that dynamically intercept and filter raw JSON documents *inside the execution pipeline* before they are ever returned to the client or written to disk.

By leveraging session contexts variables (prefixed with `@`), you can create multi-tenant architectures, strictly enforce ownership constraints, and establish precise role-based access controls without writing complex application-layer middleware.

**Detailed Example:**

Let's assume we have a `medical_records` bucket. We want to ensure that:
1. Patients can only read their own records.
2. Doctors can read and write records where they are listed as the attending physician.

```sql
-- 1. Define a READ policy for Patients
SHAPE POLICY patient_read ON medical_records FOR read USING patient_id == @session_user

-- 2. Define a READ/WRITE policy for Doctors
SHAPE POLICY doctor_access ON medical_records FOR all USING doctor_id == @session_user
```

Once the policies are attached to the bucket, the storage engine immediately begins filtering data based on the active session context:

```sql
-- Authenticate the session as a patient
SET session_user = "alice123"

-- Alice searches for records containing "blood test"
-- The engine will silently filter out ANY records not matching `patient_id == "alice123"`
SCOOP FROM medical_records MENTIONING "blood test"

-- If Alice attempts to insert a document assigning the record to someone else:
POUR INTO medical_records "rec_99" {"patient_id": "bob456", "data": "..."}
-- > Error: Security Policy Violation: Write access denied by Document-Level Security.
```

**Administrative Override (Bypassing DLS):**
If a backend service or database administrator needs to perform global aggregations, backups, or maintenance, DLS can be completely bypassed by setting the reserved context flag. This forces the Volcano executor to skip the policy evaluation layer entirely:

```sql
SET bypass_dls = "true"
```

### Step 7: Automated Pipelines (FLOW)
CleaveDB can act as its own ETL pipeline. You can create rules that automatically move or copy data when it matches a condition.

```sql
SHAPE FLOW FROM orders TO archive_orders WHEN status = "completed" ACTION MOVE
```

---

## ⚡ Performance & Benchmarks

The Python frontend utilizes a highly tuned Plan Enumerator. Current latency targets:

| Component | Metric (p99) | Throughput |
|-----------|--------------|------------|
| **Lexer/Parser** | 60.9 µs | > 25,000 ops/sec |
| **Query Planner** | 7.8 µs | > 170,000 ops/sec |
| **JSON Serialization** | 3.4 µs | > 300,000 ops/sec |

*Note: The Rust backend performance metrics scale dynamically with hardware AVX-512 availability and NVMe Disk I/O. Background processes like `HEAL ALL` utilize multi-threaded work stealing.*

---

## 🛠️ Build & Contribution Guide

### Prerequisites
- Python 3.13+
- Rust (cargo)
- `maturin` python package

### Compilation
We use `maturin` to compile the Rust backend and bind it to Python.
```bash
pip install maturin
python build.py
```

### Running the Test Suite
To execute the end-to-end integration tests (validating the Parser -> Optimizer -> Rust Engine -> Disk lifecycle):
```bash
python test_e2e.py
python test_security.py
```

## 📄 License
MIT License



