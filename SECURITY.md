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

### [Security Patch] Hardware SIMD Fallback & Soft-Delete Preservation
**Release Date**: October 3, 2026
**Impact**: High
**Components Affected**: `DropBucketStmt`, `math_ops.cpp`, `RestoreBucketStmt`.

#### 1. Hardware SIMD Illegal Instruction Crash (CDB-SEC-2026-013)
**Vulnerability**: When the engine executed the newly introduced `DISTILL` aggregation syntax, the Rust FFI directly called into C++ AVX-512 intrinsics (`_mm512_add_ps`). On CPUs that lacked AVX-512 support, the OS instantly killed the `cleavedb_server.py` process with a fatal `0xc000001d Illegal Instruction` exception, causing a complete server crash (DoS) for all connected tenants.
**Patch**: 
* Integrated `cpu_detect.h` into the C++ math layer (`math_ops.cpp`).
* The SIMD engine now performs a runtime CPU feature flag check (`cleavedb_has_avx512()`). If AVX-512 is missing, the engine gracefully falls back to a standard scalar loop, fully mitigating the hardware-level DoS vulnerability.

#### 2. DROP BUCKET Hard-Delete Override (CDB-SEC-2026-014)
**Vulnerability**: While the `DRAIN` command correctly moved documents to the tenant-isolated `_rubbish` bin, the `DROP BUCKET` statement bypassed the soft-delete layer entirely. It called directly into the Rust B+Tree engine's `delete()` method, permanently incinerating all documents and allowing authenticated tenants to inadvertently (or maliciously) wipe massive datasets without any chance of recovery.
**Patch**: 
* Overhauled `DropBucketStmt` in the AST Interpreter. `DROP BUCKET` now behaves as a massive soft-delete, iterating over all documents and safely packaging them into the `_rubbish` bin before destroying the bucket namespace.
* Introduced a native `RESTORE BUCKET` AST command, allowing tenants to seamlessly resurrect accidentally dropped buckets from the `_rubbish` ledger.

---

<details>
<summary><b>October 2, 2026 - Patch Build v3.5.10</b></summary>
<br>

### [Security Patch] Zero-Knowledge Isolation & DSL Expansion
**Release Date**: October 2, 2026
**Impact**: High
**Components Affected**: `TenantEngineProxy`, `PolicyEngine` (DSL), `DrainStmt`, `_rubbish` Bucket.

#### 1. Zero-Knowledge Tenant Isolation for Garbage Collection (CDB-SEC-2026-011)
**Vulnerability**: When removing a document via `DRAIN`, the Document ID was pushed into the global `_rubbish` system bucket without appending the tenant-level prefix (e.g., `david.`). Due to this prefix omission, the Zero-Knowledge isolation boundary filtered these documents out, preventing the original tenant from seeing or recovering their own deleted files, while potentially exposing them directly to root/global scopes without a proper tenant owner tag.
**Patch**: 
* `DrainStmt` in the AST Interpreter has been hot-patched to explicitly prefix all `_rubbish` document entries with the current execution context's `tenant` prefix.
* `SalvageStmt` and `IncinerateStmt` have been hardened to expect and validate tenant ownership markers before manipulating recycled documents, completely restoring strict Multi-Tenant isolation to the Recycle Bin.

#### 2. Document Security Level (DSL) Evaluator Expansion (CDB-SEC-2026-012)
**Vulnerability**: The CleaveQL `ENFORCE SECURITY` evaluator inside the `PolicyEngine` previously utilized a restrictive regex that only allowed string equality evaluations (e.g., `my role = "admin"`). If a numeric constraint was supplied (e.g., `IF age > 18`), the parser silently failed to evaluate it, defaulting the boolean result to `False`. This resulted in a denial-of-service (DoS) condition where users were permanently locked out of their own documents upon applying a numeric security rule.
**Patch**: 
* Injected a comprehensive recursive mathematical and boolean evaluator into `cleaveql/security.py`.
* The Policy Engine now safely extracts variables, auto-casts numeric values to `float`, and natively supports standard operational bounds (`>`, `<`, `>=`, `<=`, `==`, `!=`). Numeric lockouts are fully mitigated.

#### 3. Execution Throttling & Rate-Limiting Engine
**Feature Addition**: The proxy layer now fully supports DoS-mitigation throttling. The AST command `LIMIT <n> QUERIES PER MINUTE FOR <role>` is now securely routed and enforced to prevent rapid query-bombing across tenant graph traversals.

#### 4. Graph Path Verification Hardening (`FIND PATTERN`)
**Vulnerability**: During the deprecation of Document-Level Isolation, multi-hop traversals via `FIND PATTERN` attempted to aggressively string-match graph node GIDs containing stale isolation prefixes, resulting in mismatched memory addresses and 0-path returns.
**Patch**: 
* Edge-evaluation arrays inside the AST Interpreter are now scrubbed via dynamic index truncation prior to bond-source/target verification, restoring deep-path accuracy without breaking the new Bucket-Level isolation constraints.

</details>

<details>
<summary><b>October 1, 2026 - Patch Build v3.5.9</b></summary>
<br>

### [Security Patch] Zero-Knowledge Bucket Isolation Overhaul
**Release Date**: October 1, 2026
**Impact**: Critical
**Components Affected**: `TenantEngineProxy`, `ScoopStmt`, `SHOW BUCKETS`

#### 1. Namespace Double-Prefixing Vulnerability (CDB-SEC-2026-010)
**Vulnerability**: The execution engine was incorrectly double-prefixing bucket namespaces (e.g., querying for `david.david.users`), leading to isolated tenants incorrectly receiving empty document lists (`[]`) upon issuing `FIND EVERYTHING` queries. Furthermore, the `_bonds` bucket was vulnerable to cross-tenant pollution during relationship scans.
**Patch**:
* Overhauled `TenantEngineProxy` to enforce strict Zero-Knowledge Bucket-Level Isolation. The proxy now validates whether a bucket string is already prefixed before routing it to the core engine.
* Modified the `_bonds` global graph scanner to strictly evaluate relationship ownership against the bond's internally prefixed GID (e.g., `_bonds:{tenant}.uuid`) rather than the raw `source` and `target` body fields.

</details>

<details>
<summary><b>September 25, 2026 - Patch Build v3.5.4</b></summary>
<br>

### [Security Patch] Document Level Security (DLS) & RBAC Implementation
**Release Date**: September 25, 2026
**Impact**: High
**Components Affected**: `PolicyEngine`, `cleaveql/security.py`

#### 1. Enforce Security Ast & Role-Based Access Control (CDB-SEC-2026-009)
**Vulnerability**: Prior to this patch, CleaveDB lacked granular row-level access controls, allowing any authenticated tenant application to scoop the entirety of an exposed bucket without verifying user-context properties. 
**Patch**:
* Officially introduced the `PolicyEngine` into the AST pipeline, allowing developers to dynamically execute `ENFORCE SECURITY "policy" ON "bucket" TO ALLOW read IF ...`.
* Queries now implicitly route the active user's `$context` (e.g., `{ "user_id": "123", "role": "admin" }`) into the Policy Evaluator, silently filtering out unapproved documents before returning the `ScoopStmt` array to the client.

</details>

<details>
<summary><b>September 15, 2026 - Patch Build v3.5.1</b></summary>
<br>

### [Security Patch] AST Injection Hardening
**Release Date**: September 15, 2026
**Impact**: Medium
**Components Affected**: `Parser`, `SocketServer`

#### 1. Unsanitized Token Injection (CDB-SEC-2026-008)
**Vulnerability**: Rapidly sending malformed nested brackets within a single TCP socket stream could bypass the lexer's recursive depth limit, causing an application-level stack overflow and crashing the database engine.
**Patch**: 
* Enforced strict recursion limit boundaries in `parser.py`.
* Added TCP stream buffering sanitization to aggressively drop payloads exceeding the 16MB threshold before AST processing begins.

</details>
