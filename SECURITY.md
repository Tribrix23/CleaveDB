# Security Policy

## Reporting a Vulnerability

Because CleaveDB is a database system designed to hold sensitive data, we take security very seriously. 

If you discover a security vulnerability in the engine, the 15D Graph bonding system, the ONNX AI semantic search, or the RBAC/GBAC security policies, please DO NOT report it by creating a public GitHub issue.

Instead, please report it directly to the author/maintainer to ensure the vulnerability can be patched before it is made public. 

**Steps to report:**
1. Do not exploit the vulnerability further than necessary to verify its existence.
2. Provide a detailed summary of the vulnerability, including the CleaveQL query or script required to reproduce it.
3. Wait for our acknowledgment. We aim to respond to all security reports within 48 hours.

Once a patch is developed and verified, we will issue a security advisory and credit you for the responsible disclosure.

---

## Latest Patch: CleaveDB 3.6

### [Security Audit & Patch] Hardware SIMD Fallback & Soft-Delete Preservation
**Release Date**: October 3, 2026
**Impact**: High
**Components Affected**: `DropBucketStmt`, `math_ops.cpp`, `RestoreBucketStmt`.

#### 1. Hardware SIMD Illegal Instruction Crash (CDB-SEC-2026-013)
**Vulnerability Engine Assessment**: When the engine executed the newly introduced `DISTILL` aggregation syntax, the Rust FFI directly pushed the instruction set into the C++ AVX-512 intrinsic tier (`_mm512_add_ps`). However, the memory router failed to check the underlying host OS hardware capabilities before dispatching.
**Exploit Scenario / Attack Vector**: A malicious authenticated tenant (or an unauthenticated actor, if the endpoint lacked rate-limiting) could intentionally send a `DISTILL` aggregation query to a server cluster running on standard, non-AVX-512 hardware (such as legacy AWS EC2 instances). The moment the parser routed the query to the FFI memory space, the host CPU would trigger a fault. The OS would instantly kill the `cleavedb_server.py` process with a fatal `0xc000001d Illegal Instruction` exception. An attacker could script this in a loop to keep the database permanently offline, achieving a devastating, zero-cost remote Denial of Service (DoS) across all multi-tenant environments.
**Patch Implementation**: 
* Integrated `cpu_detect.h` into the C++ math layer (`math_ops.cpp`).
* The SIMD engine now performs a secure runtime CPU feature flag validation (`cleavedb_has_avx512()`). If AVX-512 architecture is missing, the engine gracefully reroutes the matrix calculation to a safe standard scalar loop, fully neutralizing the hardware-level DoS vulnerability.

#### 2. DROP BUCKET Hard-Delete Override (CDB-SEC-2026-014)
**Vulnerability Engine Assessment**: While the standard `DRAIN` command safely moved documents to the tenant-isolated `_rubbish` bin (acting as a soft-delete mechanism), the `DROP BUCKET` syntax entirely bypassed this protective layer. It called directly into the Rust B+Tree engine's `delete()` C-level pointer, permanently incinerating the data arrays.
**Exploit Scenario / Attack Vector**: A compromised tenant API key or a malicious insider threat with basic `DROP` privileges could issue a single command targeting a massive production namespace (e.g., `DROP BUCKET "financial_records"`). Because this command actively sidestepped the Zero-Knowledge `_rubbish` soft-delete bin, the physical B+Tree pages on the disk were aggressively zeroed out, and the Write-Ahead Log (WAL) checkpoints were permanently severed. This left the targeted organization with absolutely no native recovery option, causing catastrophic, permanent data loss that bypassed all standard system audit logs and temporal graph protections.
**Patch Implementation**: 
* Overhauled `DropBucketStmt` in the AST Interpreter. `DROP BUCKET` now operates securely as a massive soft-delete queue, iterating over all documents and packaging them heavily into the isolated `_rubbish` ledger before unlinking the bucket namespace.
* Designed and deployed a native `RESTORE BUCKET` AST function, allowing tenant administrators to seamlessly resurrect accidentally or maliciously dropped buckets in milliseconds.

---

<details>
<summary><b>October 2, 2026 - Patch Build v3.5.10</b></summary>
<br>

### [Security Audit & Patch] Zero-Knowledge Isolation & DSL Expansion
**Release Date**: October 2, 2026
**Impact**: High
**Components Affected**: `TenantEngineProxy`, `PolicyEngine` (DSL), `DrainStmt`, `_rubbish` Bucket.

#### 1. Zero-Knowledge Tenant Isolation for Garbage Collection (CDB-SEC-2026-011)
**Vulnerability Engine Assessment**: When removing a document via `DRAIN`, the Document ID was blindly pushed into the global `_rubbish` system bucket without appending the required tenant-level isolation prefix.
**Exploit Scenario / Attack Vector**: An attacker in `Tenant B` could query the shared global `_rubbish` bin. Because `Tenant A`'s deleted documents were deposited without a cryptographic tenant signature or prefix, the Zero-Knowledge firewall failed to filter them. The attacker could freely scrape and restore `Tenant A`'s sensitive deleted files (such as PII, passwords, or financial data), resulting in a critical Cross-Tenant Data Exfiltration vulnerability.
**Patch Implementation**: 
* `DrainStmt` in the AST Interpreter has been hot-patched to explicitly prefix all `_rubbish` document entries with the current execution context's `tenant` prefix.
* `SalvageStmt` and `IncinerateStmt` have been hardened to strictly expect and validate tenant ownership markers before allowing the manipulation of recycled documents.

#### 2. Document Security Level (DSL) Evaluator Expansion (CDB-SEC-2026-012)
**Vulnerability Engine Assessment**: The CleaveQL `ENFORCE SECURITY` evaluator inside the `PolicyEngine` utilized an outdated, restrictive regex that only allowed string equality evaluations. If a numeric constraint was supplied (e.g., `IF age > 18`), the parser silently failed to evaluate it, defaulting the boolean result to `False`. 
**Exploit Scenario / Attack Vector**: An attacker with partial RBAC permissions could intentionally update a bucket's security policy to rely on a numeric evaluation (e.g., `allow read if request.clearance_level > 3`). Because the parser failed to cast the mathematical boundary, it evaluated to `False` for ALL incoming requests—including requests from the global System Administrators. The attacker essentially weaponized the security engine against itself, creating an irreversible lockout condition and taking the database hostage.
**Patch Implementation**: 
* Injected a comprehensive recursive mathematical and boolean evaluator into `cleaveql/security.py`.
* The Policy Engine now safely extracts variables, auto-casts numeric values to `float`, and natively supports standard operational bounds (`>`, `<`, `>=`, `<=`, `==`, `!=`). Numeric lockouts are fully mitigated.

#### 3. Execution Throttling & Rate-Limiting Engine
**Feature Addition**: The proxy layer now fully supports DoS-mitigation throttling. The AST command `LIMIT <n> QUERIES PER MINUTE FOR <role>` is now securely routed and enforced to prevent rapid query-bombing across tenant graph traversals.

#### 4. Graph Path Verification Hardening (`FIND PATTERN`)
**Vulnerability Engine Assessment**: During the deprecation of Document-Level Isolation, multi-hop traversals via `FIND PATTERN` attempted to aggressively string-match graph node GIDs containing stale isolation prefixes, resulting in mismatched memory addresses and 0-path returns.
**Patch Implementation**: 
* Edge-evaluation arrays inside the AST Interpreter are now scrubbed via dynamic index truncation prior to bond-source/target verification, restoring deep-path accuracy without breaking the new Bucket-Level isolation constraints.

</details>

<details>
<summary><b>October 1, 2026 - Patch Build v3.5.9</b></summary>
<br>

### [Security Audit & Patch] Zero-Knowledge Bucket Isolation Overhaul
**Release Date**: October 1, 2026
**Impact**: Critical
**Components Affected**: `TenantEngineProxy`, `ScoopStmt`, `SHOW BUCKETS`

#### 1. Namespace Double-Prefixing Vulnerability (CDB-SEC-2026-010)
**Vulnerability Engine Assessment**: The execution engine was incorrectly double-prefixing bucket namespaces (e.g., querying for `david.david.users`), leading to isolated tenants incorrectly receiving empty document lists (`[]`) upon issuing `FIND EVERYTHING` queries. Furthermore, the `_bonds` bucket was vulnerable to cross-tenant pollution during relationship scans.
**Exploit Scenario / Attack Vector**: An attacker leveraging the graph API could inject malformed double-prefixed namespaces to trick the query planner into executing relationship queries against an adjacent tenant's `_bonds` bucket, potentially sniffing out private edge relationships and traversing restricted data graphs.
**Patch Implementation**:
* Overhauled `TenantEngineProxy` to enforce strict Zero-Knowledge Bucket-Level Isolation. The proxy now validates whether a bucket string is already prefixed before routing it to the core engine.
* Modified the `_bonds` global graph scanner to strictly evaluate relationship ownership against the bond's internally prefixed GID (e.g., `_bonds:{tenant}.uuid`) rather than the raw `source` and `target` body fields.

</details>

<details>
<summary><b>September 25, 2026 - Patch Build v3.5.4</b></summary>
<br>

### [Security Audit & Patch] Document Level Security (DLS) & RBAC Implementation
**Release Date**: September 25, 2026
**Impact**: High
**Components Affected**: `PolicyEngine`, `cleaveql/security.py`

#### 1. Enforce Security Ast & Role-Based Access Control (CDB-SEC-2026-009)
**Vulnerability Engine Assessment**: Prior to this patch, CleaveDB lacked granular row-level access controls, allowing any authenticated tenant application to scoop the entirety of an exposed bucket without verifying user-context properties. 
**Exploit Scenario / Attack Vector**: A standard authenticated user (e.g., a customer in a SaaS application) could execute a broad `SCOOP FROM users` query. Because the engine lacked row-level authorization limits, the query would successfully dump the entire user database, leading to a catastrophic mass data breach of all other customers residing in the same multi-tenant cluster.
**Patch Implementation**:
* Officially introduced the `PolicyEngine` into the AST pipeline, allowing developers to dynamically execute `ENFORCE SECURITY "policy" ON "bucket" TO ALLOW read IF ...`.
* Queries now implicitly route the active user's `$context` (e.g., `{ "user_id": "123", "role": "admin" }`) into the Policy Evaluator, silently filtering out unapproved documents before returning the `ScoopStmt` array to the client.

</details>

<details>
<summary><b>September 15, 2026 - Patch Build v3.5.1</b></summary>
<br>

### [Security Audit & Patch] AST Injection Hardening
**Release Date**: September 15, 2026
**Impact**: Medium
**Components Affected**: `Parser`, `SocketServer`

#### 1. Unsanitized Token Injection (CDB-SEC-2026-008)
**Vulnerability Engine Assessment**: Rapidly sending malformed nested brackets within a single TCP socket stream could bypass the lexer's recursive depth limit, causing an application-level stack overflow and crashing the database engine.
**Exploit Scenario / Attack Vector**: A remote attacker could write a script to rapidly stream millions of nested `{[[[[` tokens to the exposed `8300` port. The parser would attempt to dynamically allocate memory and trace the syntax tree recursively until it exhausted the host's RAM, triggering an Out-Of-Memory (OOM) panic and shutting down the database for all users.
**Patch Implementation**: 
* Enforced strict recursion limit boundaries in `parser.py`.
* Added TCP stream buffering sanitization to aggressively drop payloads exceeding the 16MB threshold before AST processing begins.

</details>
