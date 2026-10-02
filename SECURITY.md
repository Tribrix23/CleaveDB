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

## Latest Patch

### [Security Patch] Zero-Knowledge Isolation & DSL Expansion
**Release Date**: October 2, 2026
**Patch Hash**: `sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069`
**Impact**: High
**Components Affected**: `TenantEngineProxy`, `PolicyEngine` (DSL), `DrainStmt`, `_rubbish` Bucket.

#### 1. Zero-Knowledge Tenant Isolation for Garbage Collection (CVE-2026-CD-011)
**Vulnerability**: When removing a document via `DRAIN`, the Document ID was pushed into the global `_rubbish` system bucket without appending the tenant-level prefix (e.g., `david.`). Due to this prefix omission, the Zero-Knowledge isolation boundary filtered these documents out, preventing the original tenant from seeing or recovering their own deleted files, while potentially exposing them directly to root/global scopes without a proper tenant owner tag.
**Patch**: 
* `DrainStmt` in the AST Interpreter has been hot-patched to explicitly prefix all `_rubbish` document entries with the current execution context's `tenant` prefix.
* `SalvageStmt` and `IncinerateStmt` have been hardened to expect and validate tenant ownership markers before manipulating recycled documents, completely restoring strict Multi-Tenant isolation to the Recycle Bin.

#### 2. Document Security Level (DSL) Evaluator Expansion (CVE-2026-CD-012)
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

---

<details>
<summary><b>Previous Security Patches</b></summary>

### [Security Patch] AST Injection Hardening
**Release Date**: September 15, 2026
**Patch Hash**: `sha256:3a1e9d8b74c2f6230f81a63c72b8d9e1f54316a7d90e21bc5693c0483f124479`
**Impact**: Medium
**Components Affected**: `Parser`, `SocketServer`

#### 1. Unsanitized Token Injection (CVE-2026-CD-008)
**Vulnerability**: Rapidly sending malformed nested brackets within a single TCP socket stream could bypass the lexer's recursive depth limit, causing an application-level stack overflow and crashing the database engine.
**Patch**: 
* Enforced strict recursion limit boundaries in `parser.py`.
* Added TCP stream buffering sanitization to aggressively drop payloads exceeding the 16MB threshold before AST processing begins.

</details>
