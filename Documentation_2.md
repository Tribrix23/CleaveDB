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

## 4. Planned Capabilities Roadmap

### 4.1 `COUNT BUCKETS`
Returns the total count of user-created buckets, automatically filtering out all internal system buckets starting with `_`.

### 4.2 Cluster Node Counters
* `COUNT *_RAFT_NODES`: Returns count and status of Raft cluster nodes.
* `COUNT *_COORDINATOR_NODES`: Returns count of configured shard instances.

### 4.3 `DESCRIBE BUCKETS` & Schema Inference
Returns the complete database catalog for GUI tables, including:
* Bucket record count & storage size
* Detected field types:
  * `boolean`: Native or case-insensitive string (`true` / `false`)
  * `integer`: Numeric integers
  * `float`: Decimals
  * `date`: Inferred via `_date_` field naming or ISO 8601 formatting
  * `string`: General text
