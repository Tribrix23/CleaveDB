import io
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers.data import JsonLexer
from prompt_toolkit import Application
from prompt_toolkit.layout.containers import VSplit, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea, Frame
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
import socket
import json
import sys
import asyncio
import questionary

# --- Server Interceptor for PyInstaller ---
if "--run-server" in sys.argv:
    import cleavedb_server
    sys.argv.remove("--run-server")
    try:
        asyncio.run(cleavedb_server.main())
    except KeyboardInterrupt:
        pass
    sys.exit(0)
# ------------------------------------------
import pathlib
import getpass
import argparse
import os
from questionary import Style
custom_style = Style([
    ('qmark', 'fg:#61D6D6 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#61D6D6 bold'),
    ('pointer', 'fg:#61D6D6 bold'),
    ('highlighted', 'fg:#61D6D6 bold'),
    ('instruction', 'fg:#555555 italic')
])
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table
console = Console()


SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What is your mother's maiden name?",
    "What city were you born in?",
    "What is your favorite book?",
    "What was the make of your first car?"
]

DETAILED_HELP = {

"how": """
================================================================================
  FIND HOW THE <bond> OF <target> CHANGED BETWEEN <t1> AND <t2>
================================================================================

Examines the 4D Multi-Version Concurrency Control (MVCC) Write-Ahead Log to detect 
graph drift over a window of time. Returns all LINK and SEVER events.

Example:
    FIND HOW THE "manager" OF "users:diana" CHANGED BETWEEN "last month" AND "today"
""",

"find pattern": """
================================================================================
  FIND PATTERN ?" English Graph Pattern Matching
================================================================================

  FIND PATTERN performs a recursive Subgraph Pattern Matching query.
  Unlike traditional SQL JOINs, it traverses the hidden _bonds bucket
  to reconstruct relationships recursively in memory.

  SYNTAX:
    FIND PATTERN IN <bucket> AS <alias>
        LINKED VIA "<label>" [TO|FROM|WITH] <bucket> AS <alias>
        [LINKED VIA "<label>" [TO|FROM|WITH] <bucket> AS <alias>]*
    [WHERE <alias.field> = <value>]

  EXAMPLES:
    FIND PATTERN IN users AS u LINKED VIA "works_in" TO departments AS d LINKED VIA "located_in" TO cities AS c WHERE d.name = "AI"

  DIRECTIONS:
    TO   -> Outbound edge (source -> target)
    FROM -> Inbound edge (target -> source)
    WITH -> Undirected edge (source <-> target)
""",
"pour": """
================================================================================
  POUR — Insert / Upsert Documents
================================================================================

  POUR is the primary write command. It inserts a new document or fully
  replaces an existing one inside a bucket (collection).

  SYNTAX:
    POUR INTO <bucket> "<id>" {json}
    POUR INTO <bucket> RANDOM {json}
    POUR INTO <bucket> "<id>" {json} WITH SECRET "<password>"
    POUR INTO <bucket> "<id>" {json} EXPIRES IN <int> [SECONDS|MINUTES|HOURS|DAYS]
    POUR MANY INTO <bucket> [{...}, {...}, ...]
    POUR {json} INSIDE <bucket> "<id>" AT <field.path>

  MODIFIERS:
    RANDOM          Auto-generates a unique 64-bit hex document ID.
    WITH SECRET     Hashes the password (PBKDF2-SHA256, 100K iterations)
                    and creates an authentication record in _auth.
                    Use this to register sub-user accounts.
    MANY            Bulk-inserts an entire JSON array in one statement.
    INSIDE...AT     Injects JSON into a nested field inside an existing doc.

  EXAMPLES:
    POUR INTO users "alice" {"name": "Alice", "age": 28, "role": "admin"}
    POUR INTO events RANDOM {"type": "click", "page": "/home"}
    POUR INTO verification "token_123" {"code": 5555} EXPIRES IN 5 MINUTES
    POUR INTO users "bob" {"name": "Bob"} WITH SECRET "bobpass123"
    POUR MANY INTO products [{"gid":"p1","name":"Laptop"},{"gid":"p2","name":"Phone"}]
    POUR {"tool": "CleaveDB"} INSIDE users "alice" AT profile.skills

  NOTES:
    - All document IDs are automatically namespaced with your tenant ID.
      e.g., "alice" becomes "david.alice" if you are logged in as david.
    - If the ID already exists, POUR overwrites the entire document (upsert).
    - WITH SECRET triggers a dual-write: the document goes into the bucket
      AND the password hash goes into the hidden _auth bucket.
""",

"find": """
================================================================================
  FIND / SCOOP — Query & Retrieve Documents
================================================================================

  FIND is the primary read command. It supports 10 query modes and 12
  chainable modifiers that can be combined in any order.

  QUERY MODES:
    FIND <bucket>                                   All documents (default).
    FIND THE FIRST <n> FROM <bucket>                First N documents.
    FIND THE LAST <n> FROM <bucket>                 Last N documents.
    FIND THE TALLY OF <bucket>                      Document count.
    FIND THE HIGHEST <n> <field> FROM <bucket>      Top N by field (desc).
    FIND THE LOWEST <n> <field> FROM <bucket>       Bottom N by field (asc).
    FIND ONLY UNIQUE <field> FROM <bucket>          Distinct field values.
    FIND THE TOTAL <f> FROM <bucket> GROUPED BY <f> Grouped summation.
    FIND "<label>" OF "<source_id>"                 Graph bond traversal.
    FIND THE <r1> OF THE <r2> OF <bucket> "<id>"    Multi-hop chain traversal.

  MODIFIERS (chainable in any order):
    WHERE <field> <op> <value> [AND|OR ...]    Boolean predicates (=,!=,>,<,>=,<=)
    WHOSE <field> IS <value>                   Easy English exact match
    MENTIONING "<text>"                        Full-text keyword search
    MEANING "<text>"                           AI vector semantic search
    MATCHING "<json>"                          JSON template match
    WITH <field1>, <field2>                    Eager join (alias: INCLUDE)
    SHOW <field1>, <field2>                    Field projection (alias: YIELD)
    ARRANGED BY <field> GOING UP|DOWN          Sort (aliases: SORTED BY, ASC/DESC)
    LIMIT <n>                                  Restrict result count
    GROUPED BY <field>                         Aggregation grouping
    AS OF "<timestamp>" | yesterday            Time-travel query
    CANDIDATE                                  Include dormant conditional bonds

  EXAMPLES:
    FIND products
    FIND products WHERE price > 50 AND category = "Electronics"
    FIND users WHOSE role IS "admin"
    FIND products MENTIONING "wireless"
    FIND products MEANING "warm winter clothing" LIMIT 5
    FIND THE TALLY OF users
    FIND THE HIGHEST 3 price FROM products
    FIND ONLY UNIQUE category FROM products
    FIND EVERYTHING FROM users SHOW name, email
    FIND products ARRANGED BY price GOING DOWN LIMIT 10
    FIND EVERYTHING FROM logs AS OF yesterday
""",

"scoop": """  SCOOP is an alias for FIND. Type 'help find' for the full reference.""",

"change": """
================================================================================
  CHANGE / UPDATE — Partial Update Documents
================================================================================

  CHANGE performs a patch on an existing document. It modifies only the
  specified fields and leaves all other fields untouched.

  SYNTAX:
    CHANGE "<doc_id>" IN <bucket> TO <field> = <value>
    CHANGE <bucket> "<doc_id>" SET <field> TO <value>
    CHANGE <bucket> "<id>" SET <f1> TO <v1>, <f2> TO <v2>

  SPECIAL FEATURES:
    - Sub-Scoop Injection: Set a field from another query's result:
        CHANGE teams "devs" SET members TO (SCOOP EVERYTHING FROM users WHOSE role IS "dev")
    - Secret Update: If you SET the "secret" field, CleaveDB automatically
      re-hashes the password in the _auth bucket.

  EXAMPLES:
    CHANGE "alice" IN users TO age = 29
    CHANGE products "p1" SET price TO 1099
    CHANGE users "alice" SET address TO {"city": "New York", "zip": "10001"}
    CHANGE teams "devs" SET new_hires TO (SCOOP EVERYTHING FROM users WHOSE role IS "developer")
""",

"update": """  UPDATE is an alias for CHANGE. Type 'help change' for the full reference.""",

"drain": """
================================================================================
  DRAIN — Soft-Delete Documents
================================================================================

  DRAIN moves a document to the _rubbish bin. It is NOT a permanent delete.
  Documents in _rubbish are auto-purged after 3 days by the Cron Worker.
  You can restore them with SALVAGE before they are purged.

  SYNTAX:
    DRAIN <bucket> "<doc_id>"             Delete a specific document.
    DRAIN <bucket> WHERE <predicates>     Conditional delete.
    DRAIN <bucket> BEFORE "<datetime>"    Bulk purge by date.

  CASCADE BEHAVIOR:
    If the drained document has bonds marked ON DELETE CASCADE, all bonded
    target documents are automatically drained as well.

  EXAMPLES:
    DRAIN users "alice"
    DRAIN logs WHERE level = "debug"
    DRAIN sessions BEFORE "2024-01-01"
""",

"salvage": """
================================================================================
  SALVAGE — Restore Soft-Deleted Documents
================================================================================

  SALVAGE recovers documents from the _rubbish bin and restores them to
  their original bucket.

  SYNTAX:
    SALVAGE "<doc_id>" FROM _rubbish        Restore a specific document.
    SALVAGE EVERYTHING FROM _rubbish        Restore ALL documents.

  EXAMPLES:
    SALVAGE "alice" FROM _rubbish
    SALVAGE EVERYTHING FROM _rubbish
""",

"incinerate": """
================================================================================
  INCINERATE — Permanently Destroy Documents
================================================================================

  INCINERATE permanently removes documents from the _rubbish bin.
  This action is IRREVERSIBLE. The data is gone forever.

  SYNTAX:
    INCINERATE "<doc_id>" FROM _rubbish     Destroy a specific document.
    INCINERATE EVERYTHING FROM _rubbish     Destroy ALL rubbish.

  EXAMPLES:
    INCINERATE "alice" FROM _rubbish
    INCINERATE EVERYTHING FROM _rubbish
""",

"link": """
================================================================================
  LINK / BOND — Create 15-Dimensional Graph Relationships
================================================================================

  LINK creates a directional relationship (bond) between two documents.
  Bonds are stored in the hidden _bonds bucket and can be traversed with FIND.

  SYNTAX:
    LINK "<source>" TO "<target>" AS "<label>"
    LINK "<source>" TO "<target>" AS MUTUAL "<label>"
    LINK "<source>" TO ANY("<t1>", "<t2>") AS "<label>"

  MODIFIERS (combinable):
    MUTUAL                  Creates bonds in BOTH directions automatically.
    EXCLUSIVELY             Expires all prior bonds with the same source + label.
    ON DELETE CASCADE       Auto-deletes target when source is drained.
    WITH CONFIDENCE <float> Edge confidence weight (0.0 - 1.0).
    WITH AFFINITY <float>   Edge affinity/strength weight (0.0 - 1.0).
    EXPIRING IN <n> HOURS   Ephemeral bond — auto-expires after duration.
    EXPIRING IN <n> MINUTES Same, but in minutes.
    IF <subj> <field> IS <val>
                            Conditional bond — dormant until condition is true.
                            Subjects: source, target, their, its, his, her, my
    THROUGH "<node>"        Routes the bond through an intermediate node.
    TO ANY("<id1>", "<id2>") Creates bonds to multiple targets at once.

  EXAMPLES:
    LINK "users:alice" TO "users:bob" AS "friend"
    LINK "users:alice" TO "users:bob" AS MUTUAL "friend"
    LINK "users:alice" TO "session:s1" AS "active" EXPIRING IN 1 HOUR
    LINK "order:55" TO "users:alice" ON DELETE CASCADE
    LINK "doc:1" TO "topic:ai" AS "tagged" WITH CONFIDENCE 0.94
    LINK "users:bob" TO "product:shoes" AS "interested" WITH AFFINITY 0.87
    LINK "users:alice" TO "project:x" AS "member" EXCLUSIVELY
    LINK "users:alice" TO "file:secret.pdf" AS "can_read" IF target clearance IS "public"
    LINK "users:alice" TO ANY("team:a", "team:b") AS "belongs_to"

  TRAVERSAL (after creating bonds):
    FIND "friend" OF "users:alice"
    FIND THE friend OF THE friend OF users "alice"
    FIND RELATED "friend" FROM "users:alice"
""",

"bond": """  BOND is an alias for LINK. Type 'help link' for the full reference.""",

"sever": """
================================================================================
  SEVER / UNLINK — Destroy Graph Bonds
================================================================================

  SEVER removes bonds between two documents.

  SYNTAX:
    SEVER "<source>" FROM "<target>" AS "<label>"   Remove specific bond.
    SEVER "<source>" FROM "<target>"                 Remove ALL bonds between pair.

  EXAMPLES:
    SEVER "users:alice" FROM "users:bob" AS "friend"
    SEVER "users:alice" FROM "project:x"
""",

"unlink": """  UNLINK is an alias for SEVER. Type 'help sever' for the full reference.""",


"transaction": """
================================================================================
  CleaveQL Reference: ACID Transactions
================================================================================

  Transactions guarantee Atomicity, Consistency, Isolation, and Durability.
  If any statement fails, the entire block rolls back.

  Syntax:
    BEGIN TRANSACTION
    POUR INTO users "alice" {"money": 50}
    POUR INTO users "bob" {"money": 150}
    COMMIT
""",

"trigger": """
================================================================================
  CleaveQL Reference: Database Triggers
================================================================================

  Triggers automatically execute CleaveQL background queries on data mutation.
  Variables like `$gid` and `$field_name` are dynamically interpolated from the
  body of the inserted/modified document.

  Syntax:
    ON POUR INTO purchases RUN 'POUR INTO audit \"$gid\" {\"action\": \"item_purchased\", \"item\": \"$item\"}'
""",

"meaning": """
================================================================================
  MEANING — AI Vector Semantic Search
================================================================================

  MEANING performs hardware-accelerated semantic similarity search using a
  real neural Transformer model (all-MiniLM-L6-v2, ONNX Q8_0, ~22MB).

  HOW IT WORKS:
    1. Your search phrase is embedded into a 384-dimensional vector (<5ms).
    2. Every document's text content is also embedded.
    3. Cosine similarity is computed between the vectors.
    4. Results are ranked by _embedding_distance (0.0 - 1.0).
    5. Documents with similarity <= 0.20 are automatically filtered out.

  SYNTAX:
    FIND <bucket> MEANING "<natural language query>" [LIMIT <n>]

  EXAMPLES:
    FIND products MEANING "something warm for cold weather" LIMIT 3
    FIND articles MEANING "machine learning applications in healthcare"
    FIND recipes MEANING "quick healthy breakfast ideas"

  KEY INSIGHT:
    Unlike MENTIONING (keyword search), MEANING understands semantic
    relationships. Searching for "warm winter clothing" will match
    "Thick Wool Coat" even though those exact words don't appear.
    The Transformer model understands that coats are warm and wool is
    associated with winter.

  RESULT FORMAT:
    Each result includes an "_embedding_distance" score:
    { "gid": "products:coat", "body": {...}, "_embedding_distance": 0.57 }
""",

"mentioning": """
================================================================================
  MENTIONING — Full-Text Keyword Search
================================================================================

  MENTIONING performs a case-insensitive substring search across the entire
  JSON body of every document in the bucket.

  SYNTAX:
    FIND <bucket> MENTIONING "<text>" [LIMIT <n>]

  EXAMPLES:
    FIND products MENTIONING "wireless headphones"
    FIND articles MENTIONING "quantum computing"
    FIND logs MENTIONING "error" LIMIT 10

  COMPARISON WITH MEANING:
    MENTIONING = exact keyword substring match (fast, literal)
    MEANING    = AI semantic similarity (understands synonyms & concepts)
""",

"where": """
================================================================================
  WHERE — Boolean Predicate Filtering
================================================================================

  WHERE filters documents using boolean expressions with comparison operators.
  Multiple predicates can be chained with AND / OR.

  OPERATORS: =, ==, !=, >, <, >=, <=

  SYNTAX:
    FIND <bucket> WHERE <field> <op> <value> [AND|OR <field> <op> <value> ...]

  EXAMPLES:
    FIND products WHERE price > 100
    FIND users WHERE age >= 18 AND role = "admin"
    FIND events WHERE type = "error" OR type = "warning"
    FIND products WHERE price > 50 AND price < 200 AND category = "Electronics"

  TYPE COERCION:
    If a field contains a number and the predicate value is a numeric string,
    CleaveDB automatically converts the string to a number for comparison.
""",

"whose": """
================================================================================
  WHOSE — Easy English Field Match
================================================================================

  WHOSE is a simpler, more readable alternative to WHERE for exact equality.

  SYNTAX:
    FIND <bucket> WHOSE <field> IS <value>

  EXAMPLES:
    FIND users WHOSE role IS "admin"
    FIND products WHOSE category IS "Electronics"
    FIND employees WHOSE department IS "Engineering"
""",

"mask": """
================================================================================
  MASK — Dynamic Field Redaction
================================================================================

  MASK hides (strips) a sensitive field from query results when a condition
  is met. The field is completely removed from the JSON — never sent to
  unauthorized clients.

  SYNTAX:
    MASK "<field>" ON "<bucket>" IF <condition>

  CONDITION PATTERNS:
    IF my role != "admin"                   RBAC role check
    IF bonded as "owner" to my user_id      GBAC graph bond check
    IF @role != "doctor"                    Context variable check

  EXAMPLES:
    MASK "salary" ON "employees" IF my role != "admin"
    MASK "ssn" ON "patients" IF my role != "doctor"
    MASK "email" ON "users" IF my role != "admin"

  HOW IT WORKS:
    1. The document is retrieved normally from the Rust engine.
    2. The mask condition is evaluated against the current session context.
    3. If the condition is TRUE, the field is deleted from the result.
    4. The client never sees the original value — it's stripped server-side.

  REMOVAL:
    DROP SECURITY "salary" ON "employees"
""",

"enforce": """
================================================================================
  ENFORCE — Security Policies & Eviction Rules
================================================================================

  ENFORCE creates either a security access policy (GBAC/RBAC) or a memory
  eviction policy on a bucket.

  SECURITY POLICY SYNTAX:
    ENFORCE SECURITY "<name>" ON "<bucket>" TO ALLOW read|write IF <condition>

  EVICTION POLICY SYNTAX:
    ENFORCE POLICY ON <bucket> TO OVERWRITE CURRENT
    ENFORCE POLICY ON <bucket> TO REPLACE OLDEST UPDATES
    ENFORCE POLICY ON <bucket> TO REPLACE LEAST RECENTLY USED

  SECURITY CONDITION PATTERNS:
    IF my role = "admin"                    RBAC — check user's role
    IF bonded as "owner" to my user_id      GBAC — check graph bond exists
    IF department == @user_department       Document field vs context variable

  EXAMPLES:
    ENFORCE SECURITY "admin_only" ON "config" TO ALLOW write IF my role = "admin"
    ENFORCE SECURITY "owner_read" ON "docs" TO ALLOW read IF bonded as "owner" to my user_id
    ENFORCE POLICY ON "cache" TO REPLACE LEAST RECENTLY USED

  REMOVAL:
    DROP SECURITY "admin_only" ON "config"
""",

"drop": """
================================================================================
  DROP SECURITY — Remove Security Policies & Masks
================================================================================

  DROP SECURITY removes a named security policy and/or field mask from a
  bucket, both from memory and from persistent storage.

  SYNTAX:
    DROP SECURITY "<name>" ON "<bucket>"

  EXAMPLES:
    DROP SECURITY "admin_only" ON "config"
    DROP SECURITY "salary" ON "employees"
""",

"every": """
================================================================================
  EVERY — Background Cron Scheduler
================================================================================

  EVERY registers a recurring background task that runs inside the server's
  asyncio Cron Worker. No external job scheduler needed.

  SYNTAX:
    EVERY <n> SECONDS DO (<CleaveQL command>)
    EVERY <n> MINUTES DO (<CleaveQL command>)
    EVERY <n> HOURS DO (<CleaveQL command>)
    EVERY DAY AT MIDNIGHT DO (<CleaveQL command>)

  EXAMPLES:
    EVERY 30 SECONDS DO (SCOOP THE TALLY OF users)
    EVERY 5 MINUTES DO (DRAIN sessions WHERE expired = true)
    EVERY 1 HOUR DO (HEAL ALL)
    EVERY DAY AT MIDNIGHT DO (INCINERATE EVERYTHING FROM _rubbish)

  HOW IT WORKS:
    1. The job is saved to the hidden _cron bucket with an interval.
    2. The Cron Worker coroutine checks every 5 seconds.
    3. When current_time - last_run >= interval, it executes the command.
    4. Jobs run with admin context and full engine access.
""",

"shape": """
================================================================================
  SHAPE — Configure Buckets, Projections & Flows
================================================================================

  SHAPE declares infrastructure: bucket settings, virtual views, and
  automated data flows between buckets.

  BUCKET SYNTAX:
    SHAPE BUCKET <name> [COMPRESSION <val>] [TTL <val>] [MAX DOCUMENTS <n>] [VERSIONED]

  PROJECTION SYNTAX:
    SHAPE PROJECTION <name> FROM <bucket> [WHERE <predicates>]

  FLOW SYNTAX:
    SHAPE FLOW FROM <source> TO <dest> WHEN <expression> ACTION COPY|MOVE

  EXAMPLES:
    SHAPE BUCKET logs COMPRESSION lz4 TTL 86400 MAX DOCUMENTS 10000 VERSIONED
    SHAPE PROJECTION active_users FROM users WHERE status = "active"
    SHAPE FLOW FROM orders TO archive WHEN status = "completed" ACTION MOVE

  OPTIONS:
    COMPRESSION   Compression algorithm for stored pages.
    TTL           Time-to-live in seconds before auto-expiry.
    MAX DOCUMENTS Maximum capacity (triggers eviction when exceeded).
    VERSIONED     Enables MVCC history tracking for time-travel queries.
""",

"index": """
================================================================================
  INDEX — Create Secondary B+Tree Indexes
================================================================================

  INDEX creates a compound secondary index on one or more fields for
  O(log N) lookups instead of full bucket scans.

  SYNTAX:
    INDEX <bucket> ON (<field1>, <field2>, ...)

  EXAMPLES:
    INDEX users ON (role)
    INDEX products ON (category, price)
    INDEX employees ON (department, salary)
""",

"show": """
================================================================================
  SHOW — Display Metadata & Statistics
================================================================================

  SHOW queries the engine for internal metadata about buckets, bonds,
  indexes, and engine statistics.

  SYNTAX:
    SHOW BUCKETS      List all active buckets and their document counts.
    SHOW BONDS        List all graph bonds in the _bonds bucket.
    SHOW INDEXES      List all secondary indexes.
    SHOW STATS        Display engine-wide statistics.

  EXAMPLES:
    SHOW BUCKETS
    SHOW BONDS
""",

"describe": """
================================================================================
  DESCRIBE — Inspect Bucket Schema & Tutorials
================================================================================

  DESCRIBE profiles a bucket (document count, field stats) or displays
  built-in interactive tutorials.

  SYNTAX:
    DESCRIBE <bucket>       Bucket statistics and field coverage.
    DESCRIBE MEANING        Tutorial on how to use AI semantic search.

  EXAMPLES:
    DESCRIBE users
    DESCRIBE MEANING
""",

"heal": """
================================================================================
  HEAL — Repair & Rebuild
================================================================================

  HEAL triggers maintenance operations on the storage engine to repair
  corrupted or stale data structures.

  SYNTAX:
    HEAL ALL        Rebuild all indexes and bonds.
    HEAL BONDS      Repair graph bond structure only.
    HEAL INDEXES    Rebuild secondary indexes only.

  EXAMPLES:
    HEAL ALL
    HEAL BONDS
""",

"peer": """
================================================================================
  PEER — Query Plan Explanation & Attention Inspection
================================================================================

  PEER lets you inspect how the engine will execute a query (execution plan)
  or inspect the AI attention mechanism's statistics.

  SYNTAX:
    PEER INTO (<query>)         Print the execution plan for a query.
    PEER INTO ATTENTION         Inspect attention mechanism stats.

  EXAMPLES:
    PEER INTO (FIND products WHERE price > 100)
    PEER INTO ATTENTION
""",

"trace": """
================================================================================
  TRACE — Multi-Hop Graph Chain Traversal
================================================================================

  TRACE is a shortcut for multi-hop graph traversal. It follows a sequence
  of bond labels starting from a source document.

  SYNTAX:
    TRACE "<label1>", "<label2>" FROM "<source_id>"

  EQUIVALENT TO:
    FIND THE <label1> OF THE <label2> OF <bucket> "<id>"

  EXAMPLE:
    TRACE "manages", "manages" FROM "org:ceo"
    (Finds: CEO -> managers -> their reports)

  HOW IT WORKS:
    1. Start at the source document.
    2. Follow bonds matching the LAST label in the list.
    3. From those results, follow bonds matching the NEXT label.
    4. Continue until all labels are traversed.
    5. Return the final set of documents.
""",

"follow": """
================================================================================
  FOLLOW — Legacy Graph Traversal API
================================================================================

  FOLLOW provides full control over graph traversal with direction,
  depth limits, and bond filtering.

  SYNTAX:
    FOLLOW "<doc_id>" [THROUGH "<bond_label>"] [DIRECTION OUT|IN|BOTH]
                       [DEPTH <n>] [LIMIT <n>]

  MODIFIERS:
    THROUGH <bond>    Only traverse bonds with this label.
    DIRECTION OUT     Follow outgoing edges only.
    DIRECTION IN      Follow incoming edges only.
    DIRECTION BOTH    Follow edges in both directions.
    DEPTH <n>         Maximum number of hops.
    LIMIT <n>         Maximum number of returned documents.

  EXAMPLES:
    FOLLOW "users:alice" THROUGH "friend" DIRECTION BOTH DEPTH 3
    FOLLOW "users:alice" DIRECTION OUT DEPTH 1 LIMIT 10
""",

"distill": """
================================================================================
  DISTILL — Aggregation Pipeline
================================================================================

  DISTILL runs aggregation functions over a bucket's numeric fields.

  SYNTAX:
    DISTILL FROM <bucket> <function> OF <field>

  FUNCTIONS:
    TOTAL     Sum of all values.
    AVERAGE   Mean average.
    MIN       Minimum value.
    MAX       Maximum value.
    SPREAD    Range / variance.

  EXAMPLES:
    DISTILL FROM employees TOTAL OF salary
    DISTILL FROM scores AVERAGE OF points
    DISTILL FROM products MIN OF price
""",

"suggest": """
================================================================================
  SUGGEST — AI Bond Suggestions
================================================================================

  SUGGEST uses attention-based analysis to recommend missing logical
  relationships between your documents.

  SYNTAX:
    SUGGEST BONDS

  TIP: Run 'HEAL ALL' first to gather statistics before requesting suggestions.
""",

"authenticate": """
================================================================================
  AUTHENTICATE — Switch Session Identity
================================================================================

  AUTHENTICATE changes the current session's user context. Useful for
  testing security policies without logging out and back in.

  SYNTAX:
    AUTHENTICATE AS "<user_id>"

  EXAMPLES:
    AUTHENTICATE AS "alice"
    AUTHENTICATE AS "guest"
""",

"set": """
================================================================================
  SET — Session Context Variables
================================================================================

  SET assigns a value to a session context variable. Context variables are
  used by security policies and masks to make access control decisions.

  SYNTAX:
    SET <key> = <value>

  EXAMPLES:
    SET user = "alice"
    SET role = "admin"
    SET department = "Engineering"
    SET bypass_dls = true
""",

"rewind": """
================================================================================
  REWIND — Time-Travel Document Restoration
================================================================================

  REWIND restores a document to its state at a specific point in time
  using the MVCC history ledger.

  SYNTAX:
    REWIND "<doc_id>" TO "<timestamp>"
    REWIND "<doc_id>" TO yesterday

  EXAMPLES:
    REWIND "users:alice" TO yesterday
    REWIND "users:alice" TO "1690000000"
""",
}



HELP_TEXT = """
================================================================================
  CleaveDB 3.9.0 Manual (CleaveQL) - Complete Reference
================================================================================

1. WRITE & UPDATE (Mutations)
  POUR INTO <bucket> "<id>" {json}              Insert/upsert a document.
  POUR INTO <bucket> RANDOM {json}              Insert with auto-generated ID.
  POUR ... EXPIRES IN 5 MINUTES                 Ephemeral TTL document injection.
  POUR INTO <bucket> "<id>" {json} WITH SECRET "<pw>"
                                                Insert + register sub-account.
  POUR MANY INTO <bucket> [{...}, {...}]        Bulk insert array of documents.
  POUR {json} INSIDE <bucket> "<id>" AT <path>  Inject into nested field path.
  CHANGE "<id>" IN <bucket> TO <field> = <val>  Partial update (patch).
  CHANGE <bucket> "<id>" SET <f1> TO <v1>, <f2> TO <v2>
                                                Multi-field update.
  DRAIN <bucket> "<id>"                         Soft-delete to _rubbish bin.
  DRAIN <bucket> WHERE <predicates>             Conditional soft-delete.
  DRAIN <bucket> BEFORE "<date>"                Bulk purge by date.
  SALVAGE "<id>" FROM _rubbish                  Restore one document.
  SALVAGE EVERYTHING FROM _rubbish              Restore all documents.
  INCINERATE "<id>" FROM _rubbish               Permanently destroy one.
  INCINERATE EVERYTHING FROM _rubbish           Permanently destroy all.

2. READ & SEARCH (SCOOP Engine)
  FIND <bucket>                                 Retrieve all documents.
  (Aliases: SCOOP EVERYTHING FROM <bucket>)

  [Query Modes]
  FIND THE FIRST <n> FROM <bucket>              First N documents.
  FIND THE LAST <n> FROM <bucket>               Last N documents.
  FIND THE TALLY OF <bucket>                    Document count.
  FIND THE HIGHEST <n> <field> FROM <bucket>    Top N by field (descending).
  FIND THE LOWEST <n> <field> FROM <bucket>     Bottom N by field (ascending).
  FIND ONLY UNIQUE <field> FROM <bucket>        Distinct values for a field.
  FIND THE TOTAL <field> FROM <bucket> GROUPED BY <field>
                                                Grouped summation.

  [Modifiers - chainable in any order]
  ... WHERE <field> <op> <value> [AND|OR ...]   Boolean filter (=,!=,>,<,>=,<=).
  ... WHOSE <field> IS <value>                  Exact field match (easy English).
  ... MENTIONING "<text>"                       Full-text keyword search.
  ... MEANING "<text>"                          AI vector semantic search (ONNX).
  ... MATCHING "<json>"                         JSON structural template match.
  ... WITH <field1>, <field2>                   Eager join (Alias: INCLUDE).
  ... SHOW <field1>, <field2>                   Field projection (Alias: YIELD).
  ... ARRANGED BY <field> GOING UP|DOWN         Sort (Aliases: SORTED BY, ASC/DESC).
  ... LIMIT <n>                                 Restrict result count.
  ... GROUPED BY <field>                        Aggregation grouping.
  ... AS OF "<timestamp>" | yesterday           Time-travel historical query.
  ... CANDIDATE                                 Include dormant conditional bonds.

3. GRAPH RELATIONS & TRAVERSAL (15D Bonds)
  LINK "<src>" TO "<tgt>" AS "<label>"          Create a directional bond.
  (Aliases: BOND)

  [Bond Modifiers - combinable]
  ... AS MUTUAL "<label>"                       Bidirectional (both directions).
  ... EXCLUSIVELY                               Expires prior bonds (same src+label).
  ... ON DELETE CASCADE                         Auto-delete target when src drained.
  ... WITH CONFIDENCE <float>                   Edge confidence weight (0.0-1.0).
  ... WITH AFFINITY <float>                     Edge affinity weight (0.0-1.0).
  ... EXPIRING IN <n> HOURS|MINUTES             Ephemeral time-bound bond.
  ... IF <subject> <field> IS <value>           Conditional (dormant until true).
      Subjects: source, target, their, its, my
  ... THROUGH "<node>"                          Route through intermediate node.
  ... TO ANY("<id1>", "<id2>")                  Multi-target bond creation.

  [Bond Queries]
  FIND "<label>" OF "<source_id>"               Direct 1-hop lookup.
  FIND THE <rel1> OF THE <rel2> OF <bucket> "<id>"
                                                Deep multi-hop chain traversal.
  TRACE "<rel1>", "<rel2>" FROM "<source_id>"   Alternative chain syntax.
  FIND RELATED "<label>" FROM "<source_id>"     Bond metadata query.
  FIND CANDIDATE "<label>" OF "<id>"            Include inactive conditional bonds.
  FIND "<label>" OF "<id>" AS OF yesterday      Time-travel bond query.

  [Bond Removal]
  SEVER "<src>" FROM "<tgt>" AS "<label>"       Destroy specific bond.
  SEVER "<src>" FROM "<tgt>"                    Destroy all bonds between pair.
  (Aliases: UNLINK)

  [Legacy Graph API]
  FOLLOW "<id>" THROUGH "<bond>" DIRECTION OUT|IN|BOTH DEPTH <n> LIMIT <n>

4. DATA-LEVEL SECURITY (GBAC / RBAC / Masking)
  ENFORCE SECURITY "<name>" ON "<bucket>" TO ALLOW read|write IF <condition>
                                                Graph/Role-based access policy.
  MASK "<field>" ON "<bucket>" IF <condition>   Dynamic field redaction.
  DROP SECURITY "<name>" ON "<bucket>"          Remove policy and/or mask.
  SET <key> = <value>                           Set session context variable.
  AUTHENTICATE AS "<user_id>"                   Switch session identity.

  [Security Condition Patterns]
  ... IF my role = "admin"                      RBAC role check.
  ... IF bonded as "owner" to my user_id        GBAC graph bond check.
  ... IF department == @user_department          Document vs context field.
  ... IF @role != "viewer"                      Context vs literal.

5. MEMORY EVICTION POLICIES
  ENFORCE POLICY ON <bucket> TO OVERWRITE CURRENT
                                                Overwrite-in-place eviction.
  ENFORCE POLICY ON <bucket> TO REPLACE OLDEST UPDATES
                                                FIFO eviction (oldest first).
  ENFORCE POLICY ON <bucket> TO REPLACE LEAST RECENTLY USED
                                                LRU eviction (auto capacity: 100).

6. ANALYTICS & AGGREGATION
  FIND THE TALLY OF <bucket>                    Total document count.
  FIND THE HIGHEST <n> <field> FROM <bucket>    Top N by field value.
  FIND THE LOWEST <n> <field> FROM <bucket>     Bottom N by field value.
  FIND ONLY UNIQUE <field> FROM <bucket>        Distinct field values.
  FIND THE TOTAL <field> FROM <bucket> GROUPED BY <field>
                                                Grouped summation.
  DISTILL FROM <bucket> <func> OF <field>       Pipeline aggregation.
      Functions: TOTAL, AVERAGE, MIN, MAX, SPREAD

7. INFRASTRUCTURE & SCHEDULING
  SHAPE BUCKET <bucket> [opts]                  Configure bucket properties.
      Options: COMPRESSION <val>, TTL <val>, MAX DOCUMENTS <n>, VERSIONED
  SHAPE PROJECTION <name> FROM <bucket> [WHERE ...]
                                                Virtual materialized view.
  SHAPE FLOW FROM <src> TO <dst> WHEN <expr> ACTION COPY|MOVE
                                                Automated bucket-to-bucket flow.
  INDEX <bucket> ON (<field1>, <field2>)         Compound B+Tree secondary index.
  EVERY <n> SECONDS|MINUTES|HOURS DO (<cmd>)    Background scheduled task.
  EVERY DAY AT MIDNIGHT DO (<cmd>)              Daily midnight job.

8. DIAGNOSTICS & METADATA
  SHOW BUCKETS                                  List all active buckets.
  SHOW BONDS                                    List all graph bonds.
  SHOW INDEXES                                  List all secondary indexes.
  SHOW STATS                                    Engine statistics.
  DESCRIBE <bucket>                             Bucket doc count and field stats.
  DESCRIBE MEANING                              Built-in semantic search tutorial.
  HEAL ALL                                      Rebuild all indexes and bonds.
  HEAL BONDS                                    Repair graph bond structure.
  HEAL INDEXES                                  Rebuild secondary indexes.
  PEER INTO (<query>)                           Print internal execution plan.
  PEER INTO ATTENTION                           Inspect attention mechanism.
  SUGGEST BONDS                                 AI-suggested missing relationships.

9. LANGUAGE ALIASES
  FIND = SCOOP          UPDATE = CHANGE         LINK = BOND
  UNLINK = SEVER        TRACE = SCOOP CHAIN     SORTED BY = ARRANGED BY
  ASC = GOING UP        DESC = GOING DOWN       WITH = INCLUDE
  SHOW = YIELD          IF = ONLY WHEN (bonds)


10. ACID TRANSACTIONS & TRIGGERS
  BEGIN TRANSACTION                             Start an atomic transaction block.
  COMMIT                                        Execute and commit transaction.
  ROLLBACK                                      Abort and rollback transaction.
  ON POUR INTO <bucket> RUN '<query>'           Create a database-level trigger.
  ON CHANGE IN <bucket> RUN '<query>'
  ON DRAIN FROM <bucket> RUN '<query>'

11. SHELL COMMANDS
  help | ?                                      Show this manual.
  logout                                        End session, return to login.
  cls | clear                                   Clear terminal screen.
  exit | quit                                   Close connection and exit.

12. FOUNDATION TIER (NEW FEATURES)
  GUARD <bucket> WITH <rules>                   Document validation.
    Ex: GUARD users WITH name IS REQUIRED, age >= 0
  SHAPE BUCKET <bucket> AUDITED                 Automatic change logging.
  ENRICH <bucket> WITH <field> AS <expr>        Computed virtual fields.
    Ex: ENRICH users WITH full_name AS CONCAT(first, " ", last)
  PEER INTO COST (<query>)                      Natural language query cost/suggester.
SHAPE WEBHOOK "<name>" ON <bucket> WHEN action = "<act>" POST TO "<url>"
                                                Native outbound HTTP events.
  SHOW WEBHOOKS                                 List webhooks.
  SHAPE REPLICA <target> FROM <source> [WHERE <expr>] [SHOW <fields>]
                                                Cross-bucket selective sync.
    Ex: SHAPE REPLICA active_users FROM users WHERE status = "active" SHOW name, role
    FORECAST <bucket> PREDICT <val> OVER <time> NEXT <n> <unit> METHOD <method>
                                                  Built-in statistical prediction.
    PIPE FROM <bucket> THEN ... THEN ...            Multi-stage aggregation pipeline.
      Ex: PIPE FROM orders THEN WHERE status="completed" THEN GROUP BY region TOTAL OF revenue AS region_total
================================================================================
"""

def do_register(f):
    from rich.console import Console
    console = Console()
    console.print("\n[bold cyan]◈ REGISTER ◈[/]")
    username = questionary.text("Username:", qmark="➔", style=custom_style).ask()
    if not username: return
    password = questionary.password("Password:", qmark="➔", style=custom_style).ask()
    if not password: return
    confirm = questionary.password("Confirm password:", qmark="➔", style=custom_style).ask()
    if password != confirm:
        print("Passwords do not match.")
        return
        
    dev_password = questionary.password("Dev Password (superuser override):", qmark="➔").ask()
    
    question = questionary.select(
        "Select a security question for account recovery:",
        qmark="◈",
        pointer="➔",
        choices=SECURITY_QUESTIONS, style=custom_style
    ).ask()
    
    if not question: return
        
    print(f"\nQuestion: {question}")
    answer = questionary.text("Answer:", qmark="➔", style=custom_style).ask()
    if not answer: return
    
    req = {
        "action": "register",
        "username": username,
        "password": password,
        "dev_password": dev_password,
        "question": question,
        "answer": answer
    }
    
    f.write(json.dumps(req) + "\n")
    f.flush()
    
    resp_str = f.readline().strip()
    if not resp_str:
        print("Server disconnected.")
        sys.exit(1)
        
    resp = json.loads(resp_str)
    if isinstance(resp, list): resp = resp[0] if resp else {}
    if resp.get("status") == "ok":
        print(f"\n[+] {resp.get('message')}\n")
    else:
        print(f"\n[-] Error: {resp.get('message')}\n")

def do_login(f):
    from rich.console import Console
    console = Console()
    console.print("\n[bold cyan]◈ LOGIN ◈[/]")
    username = questionary.text("Username:", qmark="➔", style=custom_style).ask()
    if not username: return None
    password = questionary.password("Password:", qmark="➔", style=custom_style).ask()
    if not password: return None
    
    req = {
        "action": "login",
        "username": username,
        "password": password
    }
    
    f.write(json.dumps(req) + "\n")
    f.flush()
    
    resp_str = f.readline().strip()
    if not resp_str:
        print("Server disconnected.")
        sys.exit(1)
        
    resp = json.loads(resp_str)
    if isinstance(resp, list): resp = resp[0] if resp else {}
    if resp.get("status") == "ok":
        print(f"\n[+] {resp.get('message')}\n")
        return resp
    else:
        print(f"\n[-] Error: {resp.get('message')}\n")
        return False

def do_forgot(f):
    from rich.console import Console
    console = Console()
    console.print("\n[bold cyan]◈ FORGOT PASSWORD ◈[/]")
    username = questionary.text("Username:", qmark="➔", style=custom_style).ask()
    if not username: return
    
    f.write(json.dumps({"action": "forgot_step1", "username": username}) + "\n")
    f.flush()
    
    resp_str = f.readline().strip()
    if not resp_str:
        print("Server disconnected.")
        sys.exit(1)
        
    resp = json.loads(resp_str)
    if isinstance(resp, list): resp = resp[0] if resp else {}
    if resp.get("status") == "error":
        print(f"\n[-] Error: {resp.get('message')}\n")
        return
        
    print(f"\nSecurity Question: {resp['question']}")
    answer = questionary.text("Answer:", qmark="➔", style=custom_style).ask()
    if not answer: return
    new_pw = questionary.password("Enter new password:", qmark="➔", style=custom_style).ask()
    if not new_pw: return
    
    req = {
        "action": "forgot_step2",
        "username": username,
        "answer": answer,
        "new_password": new_pw
    }
    f.write(json.dumps(req) + "\n")
    f.flush()
    
    final_resp_str = f.readline().strip()
    final_resp = json.loads(final_resp_str)
    if final_resp.get("status") == "ok":
        print(f"\n[+] {final_resp.get('message')}\n")
    else:
        print(f"\n[-] Recovery failed: {final_resp.get('message')}\n")


def main():
    parser = argparse.ArgumentParser(description="CleaveDB Interactive Shell")
    parser.add_argument("-H", "--host", default="127.0.0.1", help="Server host IP")
    parser.add_argument("-p", "--port", type=int, default=8300, help="Server port number")
    args = parser.parse_args()

    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((args.host, args.port))
        except ConnectionRefusedError:
            import subprocess, time, os
            print(f"Server not found at {args.host}:{args.port}. Auto-starting background server...")
            try:
                import pathlib
                # Find the root directory where cleavedb_server.py actually lives
                exe_dir = pathlib.Path(sys.executable if getattr(sys, 'frozen', False) else __file__).parent
                
                # Check current dir, then parent, then grand-parent
                server_path = None
                root_dir = None
                for d in [exe_dir, exe_dir.parent, exe_dir.parent.parent]:
                    if (d / "cleavedb_server.py").exists():
                        server_path = str(d / "cleavedb_server.py")
                        root_dir = str(d)
                        break
                        
                if getattr(sys, 'frozen', False):
                    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    subprocess.Popen([sys.executable, "--run-server"], cwd=str(exe_dir), creationflags=flags)
                elif server_path:
                    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    # Run the server in the correct root directory
                    subprocess.Popen(["python", "cleavedb_server.py"], cwd=root_dir, creationflags=flags)
                else:
                    print(f"Error: cleavedb_server.py not found to auto-start.")
                    time.sleep(5)
                    sys.exit(1)
                
                print("Booting up database engine... (This can take up to 30 seconds for the AI Transformer and SIMD engine)")
                
                # Retry loop for up to 30 seconds
                connected = False
                for _ in range(30):
                    time.sleep(1)
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.connect((args.host, args.port))
                        connected = True
                        break
                    except Exception:
                        continue
                
                if not connected:
                    print("Auto-start failed: Timed out waiting for database engine after 30 seconds.")
                    time.sleep(5)
                    sys.exit(1)
            except Exception as e:
                print(f"Auto-start failed: {e}")
                time.sleep(5)
                sys.exit(1)

        f = s.makefile('rw')
        
        try:
            # Minimalist Teal UI
            console.print("\n[bold #61D6D6]" + r"""  ██████╗██╗     ███████╗ █████╗ ██╗   ██╗███████╗██████╗ ██████╗ 
 ██╔════╝██║     ██╔════╝██╔══██╗██║   ██║██╔════╝██╔══██╗██╔══██╗
 ██║     ██║     █████╗  ███████║██║   ██║█████╗  ██║  ██║██████╔╝
 ██║     ██║     ██╔══╝  ██╔══██║╚██╗ ██╔╝██╔══╝  ██║  ██║██╔══██╗
 ╚██████╗███████╗███████╗██║  ██║ ╚████╔╝ ███████╗██████╔╝██████╔╝
  ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚═════╝ ╚═════╝ """ + "[/]\n")
        except Exception as e:
            print(f"RICH ERROR: {e}")
            import traceback
            traceback.print_exc()

        import questionary








        auth_data = False
        while not auth_data:
            try:
                cmd = questionary.select(
                    "Welcome to CleaveDB. Please authenticate:",
                    style=custom_style,
                    qmark="◈",
                    pointer="➔",
                    instruction="(Use ↑/↓ arrows)",
                    choices=[
                        questionary.Choice("Log into an existing account", value="login"),
                        questionary.Choice("Create a new user account", value="register"),
                        questionary.Choice("Recover a lost password", value="forgot"),
                        questionary.Separator(),
                        questionary.Choice("Exit shell", value="exit")
                    ]
                ).ask()
                
                if cmd is None or cmd in ['exit', 'quit']:
                    s.close()
                    sys.exit(0)
                elif cmd == 'register':
                    do_register(f)
                elif cmd == 'login':
                    auth_data = do_login(f)
                elif cmd == 'forgot':
                    do_forgot(f)
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                sys.exit(0)
                
        import os
        os.system("cls" if os.name == "nt" else "clear")
        console.clear()
        from prompt_toolkit import PromptSession
        from prompt_toolkit.styles import Style
        session = PromptSession()

        # Minimalist Teal UI for logged in state
        console.print("\n[bold #61D6D6]" + r"""  ██████╗██╗     ███████╗ █████╗ ██╗   ██╗███████╗██████╗ ██████╗ 
 ██╔════╝██║     ██╔════╝██╔══██╗██║   ██║██╔════╝██╔══██╗██╔══██╗
 ██║     ██║     █████╗  ███████║██║   ██║█████╗  ██║  ██║██████╔╝
 ██║     ██║     ██╔══╝  ██╔══██║╚██╗ ██╔╝██╔══╝  ██║  ██║██╔══██╗
 ╚██████╗███████╗███████╗██║  ██║ ╚████╔╝ ███████╗██████╔╝██████╔╝
  ╚═════╝╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚═════╝ ╚═════╝ """ + "[/]\n")

        console.print(f"\n[+] Login successful! (Level: {auth_data.get('auth_level', 'standard')})")
        console.print("========================================")
        console.print("Type your CleaveQL commands. (Type 'help' to see all commands)")
        console.print("Type 'logout' to switch users, or 'exit' to close.")
        console.print("========================================\n")
        
        prompt_style = Style.from_dict({
            'prompt': 'ansired bold' if auth_data.get("auth_level") == "dev" else 'ansicyan bold',
        })
        prompt_text = "root@cleavedb> " if auth_data.get("auth_level") == "dev" else f"{auth_data.get('username', 'user')}@cleavedb> "
        
        logout_requested = False
        
        while True:
            try:
                cmd = session.prompt(prompt_text, style=prompt_style).strip()
            except KeyboardInterrupt:
                continue
            except EOFError:
                logout_requested = False
                break
                
            if not cmd:
                continue
                
            if cmd.lower() in ['exit', 'quit']:
                logout_requested = False
                break
                
            if cmd.lower() == 'logout':
                logout_requested = True
                break
                
            if cmd.lower() in ['cls', 'clear']:
                import os
                os.system('cls' if os.name == 'nt' else 'clear')
                continue
                
            if cmd.lower() == '?' or cmd.lower().startswith('help'):
                console.print(HELP_TEXT)
                continue
                
            s.send((cmd.replace('\n', ' ') + '\n').encode('utf-8'))
            
            response_str = s.recv(1024 * 1024).decode('utf-8').strip()
            if not response_str:
                console.print("[red]Server closed connection.[/]")
                break
                
            try:
                response_json = json.loads(response_str)
                syntax = Syntax(json.dumps(response_json, indent=2), "json", theme="monokai")
                console.print(syntax)
            except:
                console.print(response_str)
                
            console.print("") # Blank line
            
        s.close()
        if logout_requested:
            os.system("cls" if os.name == "nt" else "clear")
            console.clear()
            continue
        else:
            sys.exit(0)
    s.close()
    print("Goodbye.")

if __name__ == "__main__":
    main()
