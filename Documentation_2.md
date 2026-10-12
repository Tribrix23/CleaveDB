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

---

## 6. Phase 3: Smart Field Type & Schema Inference Engine

### 6.1 Objective
Automatically infer the semantic data types of JSON document fields stored in CleaveDB buckets so that user interfaces (such as the GUI "Database Catalogs" explorer) can accurately display what each column represents (`string`, `integer`, `float`, `boolean`, `date`, `object`, `array`).

---

### 6.2 Semantic Type Detection Rules

The engine inspects keys and values using a strict precedence hierarchy designed to prevent ambiguous type collisions:

#### 1. Containers (High Precedence)
* **Object:** Python `dict` / JSON `{...}` maps $\rightarrow$ `"object"`.
* **Array:** Python `list` / JSON `[...]` lists $\rightarrow$ `"array"`.

#### 2. Date & Timestamp Detection
* **Rule A (Field Name Patterns):**
  * Substring: Contains `_date_` (e.g. `current_date_`, `user_date_added`).
  * Prefix: Starts with `date_` (e.g. `date_entered`, `date_of_birth`, `date_created`).
  * Suffix: Ends with `_date` or `_date_` (e.g. `created_date`, `expiry_date_`).
  * Reserved Names: Matches `date`, `datetime`, `timestamp`, `created_at`, `updated_at`, `last_active`.
* **Keyword Literal Values:**
  * When string value is `"current_date_"`, `"current_date"`, `"now()"`, or `"current_timestamp"` (case-insensitive), it is inferred as `"date"` regardless of field name.
* **Rule B (Value Pattern - ISO 8601):**
  * Matches standard date formats:
    * `YYYY-MM-DD` (e.g. `2026-10-11`)
    * `YYYY/MM/DD` (e.g. `2026/10/11`)
    * `YYYY-MM-DDTHH:MM:SS` (with optional fractional seconds and timezone `Z` or `+/-HH:MM`).
* **Rule C (Unix Timestamp Epoch Range):**
  * Evaluates numeric seconds and milliseconds:
    * **Seconds Range:** $946,684,800$ (2000-01-01) to $2,524,608,000$ (2050-01-01) [10 digits].
    * **Milliseconds Range:** $946,684,800,000$ to $2,524,608,000,000$ [13 digits].
  * Heuristic Exclusion: Non-timestamp identifiers and metric fields containing `id`, `code`, `phone`, `zip`, `amount`, `price`, `count`, `num`, `balance`, `total`, `qty`, `limit`, `offset`, `rate`, `ratio` are preserved as numeric integers/floats instead of false dates.
  * Explicit Time Fields: Fields containing `time`, `timestamp`, `epoch`, `created`, `updated`, `expire`, `active`, `login`, `sync`, or `at` are classified as `"date"` over a broader range (1980 to 2100).

#### 3. Boolean Detection
* **Native Booleans:** Python `True` or `False`.
* **Case-Insensitive String Booleans:** `"true"`, `"false"`, `"TRUE"`, `"FALSE"`, `"True"`, `"False"`.

#### 4. Integer Detection
* **Native Integers:** Python `int` (strictly excluding `bool` subclasses).
* **String Integers:** Strings containing only digits (`val.isdigit()`) or signed integer format (`"-10"`, `"+42"`).

#### 5. Float Detection
* **Native Floats:** Python `float` (e.g. `15.5`, `-0.75`).
* **String Floats:** Decimal numeric strings matching `^[+-]?(?:\d+\.\d+|\d+\.|\.\d+)$` (e.g. `"15.5"`, `"-20.95"`).

#### 6. String Detection (Fallback)
* Standard UTF-8 text strings that do not match date, boolean, integer, or float patterns.

---

### 6.3 Sampling Strategy & Type Promotion

To ensure sub-millisecond query performance on buckets containing millions of records:
1. **50-Document Sampling Cap:** The schema inference engine samples at most the first **50 documents** per bucket (`docs[:50]`).
2. **Type Promotion Hierarchy:**
   * If an attribute is `None` in an initial document, it is tracked as `null` and subsequently promoted if a typed value appears in later documents.
   * If an integer is observed in one document and a float in another, the column is promoted to `"float"` (widening numeric type).
   * Fallback: Any field that only contains `None` across all 50 sampled documents defaults cleanly to `"string"`.

---

### 6.4 Exact User Query Verification

The exact statement requested:
```sql
POUR INTO users "david"{"name":"david", "age":20, "isActive": true , "date_entered":"current_date_"}
```

#### Verification with Single Bucket Inspection (`DESCRIBE BUCKET "users"`):
```json
{
  "status": "ok",
  "bucket": "users",
  "storage_engine": "Document Vector",
  "bucket_status": "Online",
  "records": 1,
  "size": "79 B",
  "size_bytes": 79,
  "schema": {
    "name": "string",
    "age": "integer",
    "isActive": "boolean",
    "date_entered": "date"
  },
  "sample": [
    {
      "name": "david",
      "age": 20,
      "isActive": true,
      "date_entered": "current_date_"
    }
  ]
}
```

#### Verification with Full Database Catalog (`DESCRIBE BUCKETS`):
```json
{
  "status": "ok",
  "count": 1,
  "catalogs": [
    {
      "name": "users",
      "storage_engine": "Document Vector",
      "status": "Online",
      "size": "79 B",
      "size_bytes": 79,
      "records": 1,
      "schema": {
        "name": "string",
        "age": "integer",
        "isActive": "boolean",
        "date_entered": "date"
      },
      "last_active": "2026-10-11T16:00:18.455000+00:00"
    }
  ]
}
```

---

### 6.5 Automated Test Suites

1. **Unit Test Suite (`tests/test_phase3_inference.py`):**
   * Covers all 8 inference rules (strings, native/string integers, native/string floats, native/string booleans, Rule A/B/C dates, containers, 50-doc sampling cap, and type promotion).
   * **Result:** `Ran 8 tests in 0.058s - OK (100% Passing)`.

2. **Live Stack E2E Test Suite (`tests/run_e2e_phase3_test.py`):**
   * Boots isolated CleaveDB server stack with Edge Gateway, TCP IPC, and REST HTTP API.
   * Executes the exact user syntax: `POUR INTO users "david"{"name":"david", "age":20, "isActive": true , "date_entered":"current_date_"}`.
   * Tests `DESCRIBE BUCKET "users"` and `DESCRIBE BUCKETS` over TCP Gateway.
   * Tests mutations and schema descriptions through the REST API `/api/v1/query`.
   * **Result:** `ALL PHASE 3 LIVE E2E CHECKS PASSED (100% SUCCESS)`.

---

## 7. Dynamic Date, Time, and Timezone Macros (`_date_`, `_time_`, `_dtz_`)

### 7.1 Overview
When documents are poured into CleaveDB via `POUR INTO`, `POUR MANY`, or modified via `CHANGE`, users can insert dynamic macro tokens in place of manual timestamps. 

Rather than storing the literal string tokens (`"_date_"`, `"_time_"`, `"_dtz_"`), CleaveDB automatically resolves these placeholders into real, instantaneous timestamps when the pour happens.

---

### 7.2 Macro Token Reference Table

| Macro Token | Replacement Description | Output Format | Live Example Value | Inferred Type |
|---|---|---|---|:---:|
| **`_date_`** | Current calendar date | `YYYY-MM-DD` | `"2026-10-12"` | **`date`** |
| **`_time_`** | Current local time of pour | `HH:MM:SS` | `"00:15:29"` | **`time`** |
| **`_dtz_`** | Current Date, Time, and Timezone | ISO 8601 with Offset | `"2026-10-12T00:15:29.750859+08:00"` | **`date`** |

> [!NOTE]
> Macro tokens are evaluated case-insensitively (`_DATE_`, `_TIME_`, `_DTZ_`) and work across top-level fields, nested objects (`{"meta": {"at": "_dtz_"}}`), array elements, and string templates (`"Snapshot on _date_ at _time_"`).

---

### 7.3 Pour Execution & Replacement Workflow

When a query such as:
```sql
POUR INTO users "david"{"name":"david", "age":20, "isActive": true, "date_entered":"_date_", "current":"_time_", "poured_dtz":"_dtz_"}
```
is executed:
1. **Dynamic Resolution:** `resolve_dynamic_macros` detects the tokens in the payload and replaces them with instantaneous system clock readings.
2. **Persistent Storage:** The underlying storage engine receives and writes the fully substituted JSON document.
3. **Event Emitted:** WebSocket mutation events and replication logs receive the concrete date/time strings.
4. **Schema Engine:** The schema inference engine detects:
   * `date_entered`: Calendar date pattern $\rightarrow$ `"date"`
   * `current`: Time pattern `HH:MM:SS` $\rightarrow$ `"time"`
   * `poured_dtz`: ISO 8601 timestamp $\rightarrow$ `"date"`

---

### 7.4 Live Verification Outputs

#### 1. Single Bucket Schema & Live Sample (`DESCRIBE BUCKET "users"`)
```json
{
  "status": "ok",
  "bucket": "users",
  "storage_engine": "Document Vector",
  "bucket_status": "Online",
  "records": 1,
  "size": "149 B",
  "size_bytes": 149,
  "schema": {
    "name": "string",
    "age": "integer",
    "isActive": "boolean",
    "date_entered": "date",
    "current": "time",
    "poured_dtz": "date"
  },
  "sample": [
    {
      "name": "david",
      "age": 20,
      "isActive": true,
      "date_entered": "2026-10-12",
      "current": "00:15:29",
      "poured_dtz": "2026-10-12T00:15:29.750859+08:00"
    }
  ]
}
```

#### 2. Database Catalogs Grid (`DESCRIBE BUCKETS`)
```json
{
  "status": "ok",
  "count": 1,
  "catalogs": [
    {
      "name": "users",
      "storage_engine": "Document Vector",
      "status": "Online",
      "size": "149 B",
      "size_bytes": 149,
      "records": 1,
      "schema": {
        "name": "string",
        "age": "integer",
        "isActive": "boolean",
        "date_entered": "date",
        "current": "time",
        "poured_dtz": "date"
      },
      "last_active": "2026-10-11T16:15:29.750859+00:00"
    }
  ]
}
```

---

### 7.5 Automated Test Verification

Two dedicated test suites verify this behavior across unit tests and real network sockets:

```powershell
# 1. Run Unit Tests (7/7 tests pass)
python -m unittest tests/test_dynamic_macros.py
Ran 7 tests in 0.057s - OK

# 2. Run Full Live Stack E2E Test (Edge Gateway + Server + REST API)
python tests/run_e2e_macros_test.py
======================================================================
   >>> ALL DYNAMIC MACRO TESTS PASSED WITH 100% SUCCESS <<<
======================================================================
```

---

## 8. Phase 4: Go Coordinator Shard Aggregation & Multi-PC Authentication Architecture

### 8.1 Architecture & Objectives

The native Go Coordinator (`coordinator.exe` located at `coordinator/src/main.go`) serves as the high-throughput, low-latency cluster entry point for CleaveDB. In distributed sharded topologies (e.g. Coordinator on PC 1, Shard 1 on PC 1, Shard 2 on PC 2), the Coordinator acts as a scatter-gather query router that fans queries out across all participating shards and consolidates cluster telemetry without data duplication.

Phase 4 introduces four core aggregation capabilities and resolves the multi-PC cluster authentication dilemma:
1. **Intelligent `COUNT BUCKETS` Deduplication (`seenBuckets`):** Scatters `SHOW BUCKETS` to all shards, gathers bucket arrays, deduplicates shared partitions using a hash set, and returns the exact distinct user bucket count across the cluster.
2. **Unified `SHOW BUCKETS` Listing:** Gathers bucket lists across all shards, filters internal `_` buckets, deduplicates, and returns an alphabetically sorted list of all active buckets in the cluster.
3. **Database Catalog Aggregation (`DESCRIBE BUCKETS`):** Aggregates shard catalog tables so each bucket appears as a single row, combining records (`shard1.records + shard2.records`), summing byte sizes (`shard1.size_bytes + shard2.size_bytes`), unioning field schemas, and adopting the newest `last_active` timestamp.
4. **Direct Cluster Node Resolution:** Answers `COUNT COORDINATOR_NODES` and `COUNT RAFT_NODES` directly from coordinator memory without shard round-trips.
5. **Multi-PC Coordinator Authentication & Tenant Isolation Architecture:** Solves the multi-machine login and multi-tenancy challenge so tenant data on remote shards (PC 2) is isolated under the user's account rather than collapsed into a global coordinator account.

---

### 8.2 Architectural Solution: Multi-PC Coordinator Authentication & Tenant Isolation

#### The Multi-PC Dilemma
When PC 1 runs the Coordinator and PC 2 runs a CleaveDB Shard:
* Clients authenticate via CleaveQL or JSON (`{"action": "login", "username": "alice", "password": "..."}`).
* In CleaveDB, multi-tenancy isolates each tenant's buckets using tenant prefixes (`alice.orders`, `alice.users`).
* **The Problem:** If PC 1 (Coordinator) were to authenticate against PC 2 using a generic service account named `"coordinator"`, all mutations across all users (Alice, Bob, Carol) on PC 2 would be namespaced as `coordinator.orders`!
  * Alice's and Bob's data would be commingled in the same bucket.
  * Alice could read Bob's documents via `SCOOP`.
  * Total loss of multi-tenant security and isolation.

#### The 2-Tier Architecture Solution

```
+-------------------------------------------------------------------------------+
|                                  CLIENT (PC 1)                                |
|          Connects to Go Coordinator (port 8305) with user credentials         |
+-------------------------------------------------------------------------------+
                                       |
                                       | 1. {"action": "login", "username": "alice", "password": "..."}
                                       v
+-------------------------------------------------------------------------------+
|                           GO COORDINATOR (PC 1 : 8305)                         |
|   - Verifies credentials against cluster auth store                           |
|   - Binds `connAuth = &AuthInfo{Username: "alice", ...}` to client TCP session |
|   - Proxies authenticated queries with transparent tenant context             |
+-------------------------------------------------------------------------------+
                 |                                               |
                 | 2a. Scatter with Auth(alice)                  | 2b. Scatter with Auth(alice)
                 v                                               v
+---------------------------------------+       +---------------------------------------+
|             SHARD 1 (PC 1)            |       |             SHARD 2 (PC 2)            |
| - Authenticates TCP session as "alice"|       | - Authenticates TCP session as "alice"|
| - Tenant context: `tenant_id="alice"` |       | - Tenant context: `tenant_id="alice"` |
| - Writes to: `alice.orders`           |       | - Writes to: `alice.orders`           |
| - Scans from: `alice.orders`          |       | - Scans from: `alice.orders`          |
+---------------------------------------+       +---------------------------------------+
```

1. **Tier 1: Transparent Tenant Context Forwarding (Client Proxy Mode)**
   * When a client connects to the Go Coordinator and authenticates (`action: "login"`), the Coordinator records the client's `*AuthInfo` in the active TCP session (`connAuth`).
   * On every subsequent query sent by this client (`POUR`, `SCOOP`, `DRAIN`, `CHANGE`, `SHOW`), if explicit auth credentials are not included in the payload, the Coordinator automatically attaches `req.Auth = connAuth`.
   * When `queryShard` dials PC 2 (the remote shard), it executes a login handshake supplying `alice`'s credentials.
   * On PC 2, the shard runs the query inside Alice's session context (`user: "alice"`, `tenant_id: "alice"`).
   * All mutations land strictly in `alice.<bucket>` on both PC 1 and PC 2.

2. **Tier 2: Coordinator Internal System Account (`_coordinator`)**
   * A dedicated internal system account (`_coordinator` or cluster internal dev token) is maintained exclusively for:
     * Cross-shard heartbeats, pings, and shard liveness probing.
     * Cluster rebalancing, cross-node replication verification, and shard discovery.
     * Global superuser database catalog inspections when initiated by cluster administrators.
   * **Rule:** The Coordinator NEVER uses the `_coordinator` account to execute end-user queries or tenant data mutations.

---

### 8.3 Aggregation & Merging Algorithms (`coordinator/src/main.go`)

#### 1. `COUNT BUCKETS` Deduplication Merge
When the client sends `COUNT BUCKETS` or `COUNT BUCKET`:
1. The Coordinator transparently rewrites the shard query to `SHOW BUCKETS` before scattering.
2. Shards reply with their local bucket arrays:
   * Shard 1: `["accounts", "events", "orders", "users"]`
   * Shard 2: `["accounts", "events", "orders", "products"]`
3. The Coordinator collects all bucket names across shards into a deduplicating hash set:
   ```go
   seenBuckets := make(map[string]bool)
   for _, r := range parsedResults {
       for _, b := range extractBuckets(r.Data) {
           if !strings.HasPrefix(b, "_") {
               parts := strings.Split(b, ".")
               cleanName := parts[len(parts)-1]
               if !strings.HasPrefix(cleanName, "_") {
                   seenBuckets[cleanName] = true
               }
           }
       }
   }
   ```
4. Returns the distinct count (`len(seenBuckets) = 5`), ignoring system `_` buckets and eliminating partition duplication:
   ```json
   [
     {
       "status": "ok",
       "count": 5,
       "type": "buckets"
     }
   ]
   ```

#### 2. `SHOW BUCKETS` Cluster Union
If the client issues `SHOW BUCKETS`, the Coordinator uses the same `seenBuckets` hash set, extracts all keys, sorts them alphabetically, and returns the unified list:
```json
[
  {
    "status": "ok",
    "count": 0,
    "data": ["accounts", "events", "orders", "products", "users"]
  }
]
```

#### 3. `DESCRIBE BUCKETS` Multi-Shard Catalog Aggregation
When shards return catalog descriptors for the same shared bucket (e.g. `orders` on Shard 1 and `orders` on Shard 2):
* **Records Combination:** `existing.Records += cat.Records` (combines document counts across shards).
* **Bytes Summation:** `existing.SizeBytes += cat.SizeBytes` (sums storage footprints).
* **Size Formatting:** `existing.Size = formatBytes(existing.SizeBytes)`.
* **Timestamp Selection:** Adopts the latest modification time: `max(existing.LastActive, cat.LastActive)`.
* **Schema Union:** Iterates over detected field types in `cat.Schema`, merging fields and preferring specific types (`integer`, `float`, `date`, `boolean`) over generic `string` or `unknown`:
  ```go
  for k, v := range cat.Schema {
      cur, exists := existing.Schema[k]
      if !exists || cur == "string" || cur == "unknown" || cur == "" {
          existing.Schema[k] = v
      }
  }
  ```
* **Single Table Entry:** The bucket appears exactly ONCE in the returned catalogs array.

#### 4. Direct Cluster Node Count (`COORDINATOR_NODES` & `RAFT_NODES`)
Intercepted and answered directly by the Coordinator process without shard network latency:
* `COUNT COORDINATOR_NODES` / `COUNT *_COORDINATOR_NODES`: Returns `len(cfg.Shards)` and the configured shard addresses.
* `COUNT RAFT_NODES` / `COUNT *_RAFT_NODES`: Returns `len(cfg.RaftNodes)`, the leader node, and replica count.

---

### 8.4 Live Multi-Shard End-to-End Test Suite

An automated live end-to-end integration test (`tests/run_e2e_phase4_test.py`) was constructed and executed to verify Phase 4:

```powershell
python tests/run_e2e_phase4_test.py
```

#### Test Execution Log:
```text
=================================================================
   CLEAVEDB PHASE 4: GO COORDINATOR SHARD AGGREGATION TEST
=================================================================

[Step 1] Booting Shard 1 (TCP port 8299)...
   Shard 1 is UP on 127.0.0.1:8299

[Step 2] Booting Shard 2 (TCP port 8319)...
   Shard 2 is UP on 127.0.0.1:8319

[Step 3] Booting Go Coordinator on port 8350...
   Go Coordinator is UP on 127.0.0.1:8350 (Configured Shards: 8299, 8319)

[Step 4] Populating partitioned data across Shard 1 and Shard 2...
   Shard 1 populated: users, orders
   Shard 2 populated: orders (shared partition), products
   Shard 1 buckets: ['accounts', 'events', 'orders', 'users']
   Shard 2 buckets: ['accounts', 'events', 'orders', 'products']
   Expected deduplicated cluster buckets (5): ['accounts', 'events', 'orders', 'products', 'users']

[Test 1] Testing COUNT BUCKETS through Coordinator (8350)...
   Coordinator COUNT BUCKETS response: [{"status":"ok","count":5,"type":"buckets"}]
   PASS: COUNT BUCKETS successfully deduplicated across shards! (Count = 5)

[Test 2] Testing SHOW BUCKETS through Coordinator (8350)...
   Coordinator SHOW BUCKETS response: [{"status":"ok","count":0,"data":["accounts","events","orders","products","users"]}]
   PASS: SHOW BUCKETS returned unified distinct list: ['accounts', 'events', 'orders', 'products', 'users']

[Test 3] Testing DESCRIBE BUCKETS through Coordinator (8350)...
   Coordinator DESCRIBE BUCKETS response:
 [
  {
    "status": "ok",
    "count": 5,
    "catalogs": [
      {
        "name": "accounts",
        "storage_engine": "Columnar LSM",
        "status": "Online",
        "size": "0 B",
        "size_bytes": 0,
        "records": 0,
        "schema": {},
        "last_active": "2026-10-11T16:37:10.160860+00:00"
      },
      {
        "name": "events",
        "storage_engine": "Columnar LSM",
        "status": "Online",
        "size": "0 B",
        "size_bytes": 0,
        "records": 0,
        "schema": {},
        "last_active": "2026-10-11T16:37:10.160911+00:00"
      },
      {
        "name": "orders",
        "storage_engine": "Document Vector",
        "status": "Online",
        "size": "114 B",
        "size_bytes": 114,
        "records": 2,
        "schema": {
          "created_date": "date",
          "customer": "string",
          "order_id": "integer",
          "total": "float"
        },
        "last_active": "2026-10-11T16:37:10.051000+00:00"
      },
      {
        "name": "products",
        "storage_engine": "Columnar LSM",
        "status": "Online",
        "size": "28 B",
        "size_bytes": 28,
        "records": 1,
        "schema": {
          "sku": "string",
          "stock": "integer"
        },
        "last_active": "2026-10-11T16:37:10.057000+00:00"
      },
      {
        "name": "users",
        "storage_engine": "Document Vector",
        "status": "Online",
        "size": "28 B",
        "size_bytes": 28,
        "records": 1,
        "schema": {
          "age": "integer",
          "name": "string"
        },
        "last_active": "2026-10-11T16:37:10.044000+00:00"
      }
    ]
  }
]
   Combined 'orders' schema union: {
    "created_date": "date",
    "customer": "string",
    "order_id": "integer",
    "total": "float"
}
   PASS: Combined records (2), summed size_bytes, and schema union verified without duplicate bucket rows!

[Test 4] Testing COUNT COORDINATOR_NODES directly on Coordinator (8350)...
   COUNT COORDINATOR_NODES response: [{"count":2,"shards":["127.0.0.1:8299","127.0.0.1:8319"],"status":"ok"}]
   PASS: COUNT COORDINATOR_NODES directly returned configured cluster shards!

[Test 5] Testing COUNT RAFT_NODES directly on Coordinator (8350)...
   COUNT RAFT_NODES response: [{"count":2,"leader":"127.0.0.1:8311","nodes":["127.0.0.1:8311","127.0.0.1:8331"],"replicas":1,"status":"ok"}]
   PASS: COUNT RAFT_NODES directly resolved without shard roundtrips!

[Test 6] Testing Multi-Tenant Auth Session Propagation through Coordinator (8350)...
   Register response: [{"status":"ok","count":0}]
   Login response: [{"status":"ok","count":0}]
   POUR response via tenant session: [{"status":"ok","count":0}]
   SCOOP response via tenant session: [{"status":"ok","count":2,"documents":[{"body":{"amount":500,"status":"paid"},"gid":"invoices:inv_001"}]}]
   PASS: Authenticated tenant session maintained and propagated to shards!

=================================================================
   ALL PHASE 4 TESTS COMPLETED WITH 100% SUCCESS!
=================================================================
```

---

### 8.5 Step-by-Step Terminal Process & Deployment Guide

This section documents the exact terminal commands required to run and connect a distributed 2-PC cluster, interact via the interactive CLI shell, and verify persistence.

#### Topology Setup
* **PC 1 (Coordinator & Shard 1):** IP `192.168.1.10`
* **PC 2 (Remote Shard 2):** IP `192.168.1.20`

---

#### Step 1: Start Shard 2 on PC 2 (The Remote Storage Machine)
Open PowerShell / Terminal on **PC 2** and run:
```powershell
python cleavedb_server.py -H 0.0.0.0 --port 8301
```
* `-H 0.0.0.0` ensures the database listens across the LAN so PC 1 can connect.
* PC 2 is now listening on TCP port `8299` as a cluster storage worker.
* **Firewall (One-time on PC 2 if blocked by Windows):**
  ```powershell
  New-NetFirewallRule -DisplayName "CleaveDB Shard" -Direction Inbound -LocalPort 8299,8300,8301 -Protocol TCP -Action Allow
  ```

---

#### Step 2: Start Shard 1 on PC 1 (Local Shard)
Open **Terminal 1** on **PC 1** and run:
```powershell
python cleavedb_server.py -H 0.0.0.0 --port 8301
```
* Runs the local shard for PC 1 on port `8299`.

---

#### Step 3: Start Go Coordinator on PC 1 (The Cluster Link)
Open **Terminal 2** on **PC 1** and run:
```powershell
.\coordinator.exe -port 8305 -shards 127.0.0.1:8299,192.168.1.20:8299
```
* `-port 8305`: Port where client applications and the CLI connect.
* `-shards`: Connects PC 1's local shard (`127.0.0.1:8299`) and PC 2's remote shard (`192.168.1.20:8299`).
* The Go Coordinator now aggregates queries across both machines.

---

#### Step 4: Open the Interactive CleaveDB Shell
Open **Terminal 3** on **PC 1** (or any client PC on the network) and run:
```powershell
python cleave_cli.py -H 127.0.0.1 -p 8305
```
1. Select **Create a new user account** or **Log into an existing account**.
2. Enter username: `john`
3. Enter password: `Password123!`
4. The shell prompt appears: `john@cleavedb> `

---

#### Step 5: Execute Queries in Terminal (Human CleaveQL Syntax)
Users in the terminal do **NOT** type raw JSON envelopes (`{ "action": ... }`). All queries are executed using standard CleaveQL commands:

1. **Insert Data (Sharded Across PC 1 and PC 2):**
   ```sql
   POUR INTO orders :ord_01 {"item": "laptop", "price": 1200}
   ```
2. **Count Buckets (Deduplicated Across Shards):**
   ```sql
   COUNT BUCKETS
   ```
   * Returns `{ "status": "ok", "count": 1, "type": "buckets" }`.
3. **Inspect Database Catalogs (Aggregated Table View):**
   ```sql
   DESCRIBE BUCKETS
   ```
   * Displays the unified `orders` catalog with merged document count, combined byte sizes, and unified field schemas.
4. **Fetch Partitioned Documents:**
   ```sql
   SCOOP FROM orders
   ```
   * Gathers and combines documents from both PC 1 and PC 2.

---

#### Step 6: Handling Server Crash & Reboot (Persistence Verification)
1. **If PC 2 crashes or powers off:**
   * Permanent key file on disk (`%APPDATA%\CleaveDB\cleavedb.key`) is untouched and never modified.
   * Sharded documents remain safely in PC 2's local data folder.
2. **Reboot PC 2:**
   ```powershell
   python cleavedb_server.py -H 0.0.0.0 --port 8301
   ```
3. **Reconnect & Query:**
   * PC 1 automatically reconnects over TCP.
   * `SCOOP FROM orders` immediately recovers all data from PC 2 without loss or key change.

---

## 9. Phase 5: Telemetry Engine & HTTP/WS Metrics API

### 9.1 Objective
The CleaveDB Telemetry Engine feeds GUI dashboards, Prometheus exporters, and real-time monitoring tools directly without forcing clients to route complex queries through the GUI. Telemetry metrics are exposed via:
1. **Public HTTP REST Endpoint:** `GET http://localhost:8303/api/metrics` (with full CORS support for browser frontends).
2. **Real-Time WebSocket Stream:** `ws://localhost:8302` (pushes an updated telemetry snapshot every 1.0 second to subscribed clients).

---

### 9.2 Metrics Collected in `cleavedb_server.py`

| Field | Type | Description |
|---|---|---|
| `requests_per_second` | `integer` | Sliding 1-second request window calculated via high-precision monotonic timestamps. Decays automatically to 0 when idle. |
| `total_requests` | `integer` | Monotonic request counter tracking all executed database queries since process startup. |
| `latency_ms` | `float` | Rolling average query execution time (ms) measured using `time.perf_counter()`. |
| `p95_latency_ms` | `float` | 95th percentile query latency (ms) across the sliding window of recent queries. |
| `p99_latency_ms` | `float` | 99th percentile query latency (ms) across the sliding window of recent queries. |
| `chart_history` | `array` | Rolling 60-second array of `[timestamp, req_per_sec, latency_ms]` points for the Live Stream chart. |
| `storage` | `object` | Disk usage for local database directory (`total_gb`, `used_gb`, `free_gb`, `used_percent`) via `shutil.disk_usage()`. |
| `databases` | `array` | List of all user buckets with document counts (`records`), human/byte sizes (`size`, `size_bytes`), storage engine type, inferred schemas, and online status. |
| `cluster` | `object` | Raft consensus status (`is_leader`, `leader`, `node_id`, `status`, `has_quorum`, `peer_nodes`) and active port map. |

---

### 9.3 Telemetry Snapshot JSON Schema Reference

```json
{
  "status": "ok",
  "timestamp": 1791763376,
  "requests_per_second": 24,
  "total_requests": 1420,
  "latency_ms": 1.45,
  "p95_latency_ms": 3.20,
  "p99_latency_ms": 5.10,
  "chart_history": [
    [1791763317, 0, 0.0],
    [1791763376, 24, 1.45]
  ],
  "storage": {
    "total_gb": 237.33,
    "used_gb": 232.13,
    "free_gb": 5.20,
    "used_percent": 97.81
  },
  "databases": [
    {
      "name": "orders",
      "full_name": "orders",
      "tenant": "default",
      "records": 500,
      "size": "12.4 KB",
      "size_bytes": 12700,
      "storage_engine": "Document Vector",
      "schema": {
        "item": "string",
        "price": "integer",
        "order_date": "date"
      },
      "status": "Online"
    }
  ],
  "cluster": {
    "node_id": "127.0.0.1:8311",
    "is_leader": true,
    "leader": "127.0.0.1:8311",
    "status": "leader",
    "has_quorum": true,
    "peer_nodes": [],
    "active_ports": {
      "gateway": 8300,
      "tcp": 8299,
      "websocket": 8302,
      "http_rest": 8303,
      "coordinator": 8305,
      "raft": 8311
    }
  }
}
```

---

### 9.4 Terminal Testing & Dashboard Integration

#### 1. Fetching Telemetry via HTTP (cURL / PowerShell)
* **cURL:**
  ```bash
  curl http://localhost:8303/api/metrics
  ```
* **PowerShell:**
  ```powershell
  Invoke-RestMethod -Uri http://localhost:8303/api/metrics | ConvertTo-Json -Depth 5
  ```

#### 2. Streaming Telemetry via WebSocket (`ws://localhost:8302`)
Clients subscribe to real-time 1-second telemetry ticks using two options:

* **Option A: Direct Path Connection**
  Connect your WebSocket client directly to `ws://localhost:8302/api/metrics`. The server immediately transmits an acknowledgment and initiates the 1-second telemetry broadcast stream.

* **Option B: Subscription Action**
  Connect to `ws://localhost:8302` and send:
  ```json
  {"action": "subscribe_metrics"}
  ```
  The server responds with `event: "metrics_subscribed"` and broadcasts full telemetry packets every 1.0 second.

---

### 9.5 Automated Test Verification
Run the Phase 5 test suite to verify HTTP CORS endpoints, sliding window decays, percentiles, and live WebSocket streaming:
```powershell
python tests/test_phase5_telemetry.py
```
**Test Results:**
```text
..........
----------------------------------------------------------------------
Ran 10 tests in 7.881s

OK
```







