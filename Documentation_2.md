# CleaveDB 4.0.2 - Extended Architecture & Feature Documentation

This document covers the newly added distributed networking capabilities, installer packaging, security guardrails, and catalog enhancements introduced in **CleaveDB v4.0.2**.

---

## 1. Multi-PC Networking & Distributed Clusters

### 1.1 Port Map Reference
When starting the CleaveDB server stack (base port `8301`), the following ports are coordinated:

| Port | Service | Protocol | Description |
|---|---|---|---|
| **8300** | Rust Edge Gateway | TCP | Public client entrypoint (`cleaveshell.exe`, CLI, SDKs) |
| **8299** | Python Server IPC | TCP | Internal loopback IPC bridge |
| **8302** | WebSocket Server | WS | Real-time push subscriptions and event broadcasts |
| **8303** | REST API Server | HTTP | Standard HTTP endpoint for CRUD and query operations |
| **8305** | Go Coordinator | TCP | Scatter-gather distributed shard coordinator |
| **8311** | Raft Consensus Node | TCP | Node-to-node replication consensus (`pysyncobj`) |

---

### 1.2 Accessing the Live Server from Another PC (Client → Server)

#### Step 1: Open Inbound Windows Firewall
On the server PC, open PowerShell as Administrator and run:
```powershell
New-NetFirewallRule -DisplayName "CleaveDB Inbound" -Direction Inbound -LocalPort 8300,8302,8303,8305,8311 -Protocol TCP -Action Allow
```

#### Step 2: Start the Server on All Interfaces
```bash
# With Python:
python cleavedb_server.py -H 0.0.0.0

# With compiled binary:
cleaveshell.exe --run-server -H 0.0.0.0
```

#### Step 3: Connect from a Remote Client PC
Assuming the Server PC LAN IP is `192.168.1.10`:

* **CleaveShell / CLI:**
  ```bash
  cleaveshell.exe -H 192.168.1.10 -p 8300
  ```
* **HTTP REST API:**
  ```bash
  curl http://192.168.1.10:8303/api/<bucket>/<doc_id>
  ```
* **WebSocket Client:**
  ```text
  ws://192.168.1.10:8302
  ```
* **Node.js SDK (`cleavedb`):**
  ```javascript
  const client = new CleaveDB({ host: '192.168.1.10', port: 8300 });
  ```

---

### 1.3 Multi-Node Cluster Configurations

#### Option A: Raft Consensus Cluster (State Replication)
Both nodes participate in a shared state machine. All writes (`POUR`, `CHANGE`, `DRAIN`) replicate synchronously across all nodes.

* **On Computer 1 (`192.168.1.10`):**
  ```bash
  cleaveshell.exe --run-server -H 0.0.0.0 --node-ip 192.168.1.10 --raft-port 8311 --peers 192.168.1.20:8311
  ```
* **On Computer 2 (`192.168.1.20`):**
  ```bash
  cleaveshell.exe --run-server -H 0.0.0.0 --node-ip 192.168.1.20 --raft-port 8311 --peers 192.168.1.10:8311
  ```

---

#### Option B: Distributed Sharding via Go Coordinator
Each PC runs an independent CleaveDB shard instance. The Coordinator scatters queries across both PCs and aggregates results.

* **On Computer 1 (`192.168.1.10`):**
  ```cmd
  # Terminal 1: Run database shard
  cleaveshell.exe --run-server -H 0.0.0.0

  # Terminal 2: Run coordinator
  coordinator.exe -port=8305 -shards=192.168.1.10:8300,192.168.1.20:8300
  ```

* **On Computer 2 (`192.168.1.20`):**
  ```cmd
  # Terminal 1: Run database shard
  cleaveshell.exe --run-server -H 0.0.0.0

  # Terminal 2: Connect client to Coordinator
  cleaveshell.exe -H 192.168.1.10 -p 8305
  ```

---

## 2. Standalone Binary & Installer (v4.0.2)

### 2.1 Installer Package Details
* **Installer Path:** `dist/CleaveDB-v4.0.2-Setup.exe`
* **Installed Binaries:**
  1. `cleaveshell.exe`: Dual-mode executable (Interactive Shell + Database Server via `--run-server`).
  2. `coordinator.exe`: Native Go shard scatter-gather binary.
  3. `edge_gateway.exe`: Native Rust high-throughput async TCP gateway.
* **System Integration:** Automatically registers all binaries in the Windows system `PATH`.

### 2.2 GUI Sidecar Integration (No Python Required)
Modern GUI apps (Electron, PyQt, WPF, Flutter) can launch CleaveDB as a silent background sidecar:

```python
import subprocess

# Launch silent background server
db = subprocess.Popen(
    ["cleaveshell.exe", "--run-server"],
    creationflags=subprocess.CREATE_NO_WINDOW
)
```

```javascript
// In Node.js / Electron:
const { spawn } = require('child_process');
const db = spawn('cleaveshell.exe', ['--run-server'], {
  windowsHide: true,
  stdio: 'ignore'
});
```

---

## 3. Keyword Guardrails & Bucket Protection (Phase 1)

### 3.1 Objective
Prevent users from writing to or creating buckets with reserved catalog names (like `buckets`, `bonds`, `links`) that would collide with catalog queries (`SHOW BUCKETS`, `COUNT BUCKETS`, `DESCRIBE BUCKETS`).

### 3.2 Reserved System Keywords
The following bucket names are strictly reserved:
```python
RESERVED_BUCKET_NAMES = {
    "buckets", "bucket", "bonds", "bond", "links", "link",
    "indexes", "index", "stats", "webhooks", "views", "nodes",
    "coordinator", "raft", "meaning"
}
```

### 3.3 Four-Layer Guardrail Defense

| Layer | Location | Behavior When Blocked |
|---|---|---|
| **1. Parser AST** | `cleaveql/parser.py` | Rejects `POUR INTO buckets`, `CHANGE buckets`, `DRAIN buckets` with immediate `ParseError`. |
| **2. Interpreter** | `cleaveql/interpreter.py` | `_validate_bucket_mutation` checks runtime mutation statements (`PourStmt`, `PourManyStmt`, `ChangeStmt`, `DrainStmt`). |
| **3. REST API** | `cleavedb_server.py` | Blocks `POST /api/buckets`, `PUT /api/buckets/...`, `DELETE /api/buckets/...` with HTTP `400` / `403`. |
| **4. Storage Engine** | `storage/src/python.rs` | Native Rust `CleaveDB::pour` check prevents low-level Python driver bypass. |

### 3.4 System Bucket Isolation
Buckets starting with `_` (e.g. `_auth`, `_ttl`, `_bonds`, `_views`) cannot be written directly by standard users:
* `POUR INTO _internal "1" {"x": 1}` $\rightarrow$ Rejected: `Cannot write directly to system bucket '_internal'.`
* Standard access requires elevated `dev` authentication.

---

## 4. CleaveQL Query Language Extensions (Phase 2)

Phase 2 introduces dedicated telemetry, cluster inspection, and catalog statements tailored directly for database administration and GUI dashboard integrations (such as the CleaveDB Telemetry Dashboard).

---

### 4.1 `COUNT BUCKETS` (or `COUNT BUCKET`)

* **Purpose:** Returns the total count of user-created buckets.
* **Filtering:** Automatically and strictly ignores all internal system buckets starting with `_` (`_auth`, `_ttl`, `_bonds`, `_rubbish`, `_views`, `_webhooks`, `_replicas`, `_cron`, etc.).
* **Syntax:**
  ```sql
  COUNT BUCKETS;
  COUNT BUCKET;
  ```
* **Output Structure:**
  ```json
  [
    {
      "status": "ok",
      "count": 9,
      "type": "buckets"
    }
  ]
  ```

---

### 4.2 `COUNT RAFT_NODES` (and `COUNT *_RAFT_NODES`)

* **Purpose:** Inspects the active PySyncObj Raft consensus cluster and returns the total node count, elected leader address, number of replicas, and list of all active node addresses.
* **Syntax:**
  ```sql
  COUNT RAFT_NODES;
  COUNT *_RAFT_NODES;
  ```
* **Output Structure:**
  ```json
  [
    {
      "status": "ok",
      "count": 3,
      "leader": "clv-node-01",
      "replicas": 2,
      "nodes": [
        "127.0.0.1:8311",
        "192.168.1.20:8311",
        "192.168.1.30:8311"
      ]
    }
  ]
  ```

---

### 4.3 `COUNT COORDINATOR_NODES` (and `COUNT *_COORDINATOR_NODES`)

* **Purpose:** Inspects the distributed sharding layer and returns the count of active configured shards along with their network addresses.
* **Syntax:**
  ```sql
  COUNT COORDINATOR_NODES;
  COUNT *_COORDINATOR_NODES;
  ```
* **Output Structure:**
  ```json
  [
    {
      "status": "ok",
      "count": 2,
      "shards": [
        "192.168.1.10:8300",
        "192.168.1.20:8300"
      ]
    }
  ]
  ```

---

### 4.4 `DESCRIBE BUCKETS` (Full Database Catalog)

* **Purpose:** Returns the complete database catalog for all user buckets (excluding `_` system buckets). Formatted directly for GUI "Database Catalogs" grid views.
* **Fields per Bucket:**
  * `name`: Identifier of the bucket (e.g. `analytics_events_prod`).
  * `storage_engine`: Inferred storage engine (`"Document Vector"` or `"Columnar LSM"`).
  * `status`: Current availability status (`"Online"`).
  * `size`: Human-readable storage footprint (e.g. `450 KB`, `8.2 GB`).
  * `size_bytes`: Exact byte size of the bucket's document payloads.
  * `records`: Total document count inside the bucket.
  * `schema`: Detected key-value dictionary mapping field names to inferred data types.
  * `last_active`: ISO 8601 UTC timestamp of the most recent document insert, update, or read.
* **Syntax:**
  ```sql
  DESCRIBE BUCKETS;
  DESCRIBE BUCKET;
  ```
* **Output Structure:**
  ```json
  [
    {
      "status": "ok",
      "count": 1,
      "catalogs": [
        {
          "name": "analytics_events_prod",
          "storage_engine": "Columnar LSM",
          "status": "Online",
          "size": "450 KB",
          "size_bytes": 460800,
          "records": 1200,
          "schema": {
            "user_id": "string",
            "event_type": "string",
            "count": "integer",
            "is_active": "boolean",
            "event_date_": "date"
          },
          "last_active": "2026-10-11T20:30:00.000000+00:00"
        }
      ]
    }
  ]
  ```

---

### 4.5 `DESCRIBE BUCKET "<bucket_name>"` (Single Bucket Schema & Sample)

* **Purpose:** Inspects a single bucket in detail, providing its field types, record counts, storage size, and a live document sample.
* **Syntax:**
  ```sql
  DESCRIBE BUCKET "users";
  DESCRIBE BUCKET users;
  DESCRIBE "users";
  DESCRIBE users;
  ```
* **Output Structure:**
  ```json
  [
    {
      "status": "ok",
      "bucket": "users",
      "storage_engine": "Document Vector",
      "bucket_status": "Online",
      "records": 10,
      "size": "12.4 KB",
      "size_bytes": 12697,
      "schema": {
        "name": "string",
        "age": "integer",
        "isactive": "boolean",
        "current_date_": "date"
      },
      "sample": [
        {
          "name": "john",
          "age": 15,
          "isactive": true,
          "current_date_": ""
        }
      ]
    }
  ]
  ```

---

### 4.6 Intelligent Field Data Type Inference Rules

CleaveQL's schema analyzer scans documents across a bucket and determines field types using deterministic rules:

| Type | Inference Rule / Detection Criteria | Example Inputs |
|---|---|---|
| **`date`** | Field name contains `_date_`, starts with `date_`, ends with `_date`/`_date_`, or is named `date`, `datetime`, `timestamp`, `created_at`, `updated_at`. Also detected if string matches ISO 8601 (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ`). | `"current_date_": ""`, `"date_of_birth": "2000-01-01"`, `"event_date": "2026-10-11"` |
| **`boolean`** | Native JSON boolean (`true` / `false`) or case-insensitive string boolean. | `true`, `false`, `"true"`, `"False"`, `"TRUE"` |
| **`integer`** | Integer numbers (excluding bool). | `15`, `0`, `-42` |
| **`float`** | Floating-point decimal numbers. | `19.99`, `0.001` |
| **`array`** | JSON lists. | `["tag1", "tag2"]` |
| **`object`** | Nested JSON objects/dictionaries. | `{"env": "prod", "tier": 1}` |
| **`string`** | General textual values not matching the rules above. | `"john"`, `"ACTIVE"` |

---

### 4.7 Go Coordinator Distributed Shard Merging

When queries pass through the native Go Coordinator (`coordinator.exe` on port `8305`), the Coordinator scatter-gathers queries across configured shards and intelligently merges telemetry:

1. **`DESCRIBE BUCKETS`:**
   * Catalogs across shards are unified by bucket `name` into a single entry (zero duplicate rows).
   * Record counts (`records`) and payload sizes (`size_bytes`) are summed across shards.
   * Schemas are unioned to discover all active fields across shards.
   * `last_active` is updated to the newest timestamp across all shards.
2. **`DESCRIBE BUCKET "<name>"`:**
   * Combines record counts and sizes.
   * Unions schemas and merges document samples (deduplicating by `gid`).
3. **`COUNT COORDINATOR_NODES`:**
   * Answered instantly by the Coordinator without scattering, returning `cfg.Shards`.

---

## 5. Phase 2 Verification & Live Test Results

### 5.1 Test Methodology & Architecture

Phase 2 validation was performed across two distinct testing tiers to guarantee both unit-level algorithm correctness and full end-to-end network stack integrity:

1. **Storage Unit Test Tier (`tests/test_phase2_catalog.py`):**
   * Uses isolated temporary directories (`tempfile.TemporaryDirectory`).
   * Tests parser tokenization, AST generation, AST errors on keyword mutations, and interpreter execution directly against native PyO3 `cleavedb3_storage.CleaveDB`.
   * **Result:** 8/8 tests passed in **0.053s** (**100% OK**).

2. **Live Multi-Tier Network E2E Tier (`tests/run_e2e_phase2_test.py`):**
   * Automatically boots `cleavedb_server.py` on TCP loopback port `8299`.
   * Spawns `edge_gateway.exe` on public port `8300`.
   * Spawns `coordinator.exe` on port `8305`.
   * Executes queries sequentially through live TCP sockets (`127.0.0.1:8300` and `127.0.0.1:8305`), verifying socket streaming, JSON payload wrapping/unwrapping, and cross-process telemetry.
   * **Result:** 9/9 integration tests passed (**100% SUCCESS**).

---

### 5.2 End-to-End Test Matrix & Verification Log

| Test # | Test Case | Target Endpoint | Status | Verified Behavior |
|---|---|---|:---:|---|
| **Test 1** | `COUNT BUCKETS` (initial) | `TCP 127.0.0.1:8300` | **PASS** | Returned `count: 0`. Any system buckets starting with `_` strictly omitted. |
| **Test 2** | `COUNT RAFT_NODES` & `COUNT *_RAFT_NODES` | `TCP 127.0.0.1:8300` | **PASS** | Successfully inspected Raft state: `leader: "127.0.0.1:8311"`, `nodes: ["127.0.0.1:8311"]`, `replicas: 0`. |
| **Test 3** | `COUNT COORDINATOR_NODES` & `COUNT *_COORDINATOR_NODES` | `TCP 127.0.0.1:8300` | **PASS** | Returned `count: 1`, `shards: ["127.0.0.1:8300"]`. |
| **Test 4** | Document Insert (`POUR INTO ...`) | `TCP 127.0.0.1:8300` | **PASS** | Injected documents containing all 7 data types into `analytics_events_prod` and `hardware_inventory`. |
| **Test 5** | `COUNT BUCKETS` (post-insert) | `TCP 127.0.0.1:8300` | **PASS** | Count dynamically incremented from `0` to `2`. |
| **Test 6** | `DESCRIBE BUCKETS` (Full Database Catalog) | `TCP 127.0.0.1:8300` | **PASS** | Returned table catalog containing storage engines, byte sizes, record counts, and inferred schemas for all user buckets. |
| **Test 7** | `DESCRIBE BUCKET "analytics_events_prod"` | `TCP 127.0.0.1:8300` | **PASS** | Single-bucket schema inspection succeeded with schema and raw document samples. |
| **Test 8** | Keyword Guardrail Check (`POUR INTO buckets`) | `TCP 127.0.0.1:8300` | **PASS** | Mutation blocked with ParseError: `Cannot use reserved keyword 'buckets' as a bucket name.` |
| **Test 9** | `COUNT COORDINATOR_NODES` (Direct Coordinator) | `TCP 127.0.0.1:8305` | **PASS** | Native Go Coordinator binary intercepted and responded directly from internal memory without shard round-trips. |

---

### 5.3 Live Captured Payloads

#### 1. Full Database Catalog (`DESCRIBE BUCKETS`)
```json
[
  {
    "status": "ok",
    "count": 2,
    "catalogs": [
      {
        "name": "analytics_events_prod",
        "storage_engine": "Columnar LSM",
        "status": "Online",
        "size": "247 B",
        "size_bytes": 247,
        "records": 1,
        "schema": {
          "age": "integer",
          "birth_date": "date",
          "created_at": "date",
          "current_date_": "date",
          "isactive": "boolean",
          "isactive_str": "boolean",
          "name": "string",
          "profile": "object",
          "score": "float",
          "tags": "array"
        },
        "last_active": "2026-10-11T15:40:10.423000+00:00"
      },
      {
        "name": "hardware_inventory",
        "storage_engine": "Document Vector",
        "status": "Online",
        "size": "128 B",
        "size_bytes": 128,
        "records": 1,
        "schema": {
          "expiry_date_": "date",
          "in_stock": "boolean",
          "price": "float",
          "quantity": "integer",
          "sku": "string",
          "title": "string"
        },
        "last_active": "2026-10-11T15:40:10.456000+00:00"
      }
    ]
  }
]
```

#### 2. Single Bucket Schema Inspector (`DESCRIBE BUCKET "analytics_events_prod"`)
```json
[
  {
    "status": "ok",
    "bucket": "analytics_events_prod",
    "storage_engine": "Columnar LSM",
    "bucket_status": "Online",
    "records": 1,
    "size": "247 B",
    "size_bytes": 247,
    "schema": {
      "age": "integer",
      "birth_date": "date",
      "created_at": "date",
      "current_date_": "date",
      "isactive": "boolean",
      "isactive_str": "boolean",
      "name": "string",
      "profile": "object",
      "score": "float",
      "tags": "array"
    },
    "sample": [
      {
        "name": "john",
        "age": 15,
        "isactive": "true",
        "isactive_str": "false",
        "current_date_": "",
        "birth_date": "2000-05-15",
        "created_at": "2026-10-11T12:00:00Z",
        "score": 95.5,
        "tags": ["engineer", "admin"],
        "profile": {
          "location": "San Francisco"
        }
      }
    ]
  }
]
```

#### 3. Raft Cluster Inspection (`COUNT RAFT_NODES`)
```json
[
  {
    "status": "ok",
    "count": 1,
    "leader": "127.0.0.1:8311",
    "replicas": 0,
    "nodes": [
      "127.0.0.1:8311"
    ]
  }
]
```

#### 4. Shard Coordinator Inspection (`COUNT COORDINATOR_NODES`)
```json
[
  {
    "status": "ok",
    "count": 1,
    "shards": [
      "127.0.0.1:8300"
    ]
  }
]
```

#### 5. Keyword Protection Failure Payload (`POUR INTO buckets`)
```json
[
  {
    "status": "error",
    "message": "Error at 'buckets': Cannot use reserved keyword 'buckets' as a bucket name. This name is reserved for CleaveQL catalog commands."
  }
]
```

---

### 5.4 Schema Inference Proof Matrix

During live test execution, document fields were evaluated against the schema inference engine with the following verified outcomes:

| Field Key | Input Value | Inferred Type | Verification Rule Triggered |
|---|---|:---:|---|
| `"name"` | `"john"` | **`string`** | Standard UTF-8 text string |
| `"age"` | `15` | **`integer`** | Native integer number |
| `"isactive"` | `true` | **`boolean`** | Native boolean type |
| `"isactive_str"` | `"false"` | **`boolean`** | Case-insensitive boolean string parser |
| `"in_stock"` | `"TRUE"` | **`boolean`** | Uppercase boolean string parser |
| `"current_date_"` | `""` | **`date`** | Key contains `_date_` substring rule |
| `"expiry_date_"` | `"never"` | **`date`** | Key contains `_date_` substring rule |
| `"birth_date"` | `"2000-05-15"` | **`date`** | Suffix `_date` & ISO 8601 regex pattern |
| `"created_at"` | `"2026-10-11T12:00:00Z"` | **`date`** | Key named `created_at` & ISO 8601 pattern |
| `"score"` | `95.5` | **`float`** | Floating-point decimal number |
| `"price"` | `1999.99` | **`float`** | Floating-point decimal number |
| `"tags"` | `["engineer", "admin"]` | **`array`** | JSON list sequence |
| `"profile"` | `{"location": "San Francisco"}` | **`object`** | Nested JSON key-value dictionary |

---

### 5.5 How to Re-Run Tests

To execute tests at any time:

```bash
# Run unit tests directly:
python -m unittest tests/test_phase2_catalog.py

# Run full live stack E2E integration test (Edge Gateway + Server + Coordinator):
python tests/run_e2e_phase2_test.py
```


