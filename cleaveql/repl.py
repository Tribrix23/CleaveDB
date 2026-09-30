import sys
from .lexer import Lexer
from .parser import Parser, ParseError
from .semantic import SemanticAnalyzer
from .interpreter import Interpreter
from .formatter import Formatter

def start_repl(engine=None):
    print("CleaveDB 3.0 REPL")
    print("Type 'exit' or 'quit' to leave. Type 'help' for commands.\n")
    
    analyzer = SemanticAnalyzer()
    interpreter = Interpreter(engine)
    formatter = Formatter()
    
    buffer = ""
    while True:
        try:
            prompt = "cleavedb> " if not buffer else "      ... "
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        
        if line.strip().lower() in ('exit', 'quit'):
            print("Goodbye!")
            break
        if line.strip().lower() in ('cls', 'clear'):
            import os
            os.system('cls' if os.name == 'nt' else 'clear')
            continue
        if line.strip().lower() == 'help':
            print_help()
            continue
        
        buffer += line + "\n"
        
        try:
            lexer = Lexer(buffer)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            stmts = parser.parse()
            
            if stmts:
                errors = analyzer.analyze(stmts)
                if errors:
                    for err in errors:
                        print(f"  Semantic error: {err.message}")
                        if err.suggestion:
                            print(f"  Did you mean: {err.suggestion}?")
                else:
                    results = interpreter.execute(stmts)
                    for r in results:
                        print(formatter.format_json(r))
            buffer = ""
        except ParseError as e:
            print(f"  Parse error: {e}")
            buffer = ""
        except Exception as e:
            print(f"  Error: {e}")
            buffer = ""

def print_help():
    help_text = """================================================================================
  CleaveDB 3.0 Manual (CleaveQL) - Complete Comprehensive Reference
================================================================================

1. WRITE & UPDATE (Mutations)
  POUR INTO <bucket> "<id>" {json}           - Insert/upsert document.
  POUR MANY INTO <bucket> [{json}, {json}]   - Bulk insert documents.
  CHANGE <id> IN <bucket> TO <field> = <val> - Update specific fields.
  DRAIN <bucket> "<id>"                      - Move document to _rubbish bin.
  DRAIN <bucket> BEFORE "<date>"             - Bulk move old documents to _rubbish.
  SALVAGE "<id>" FROM _rubbish               - Restore specific document from rubbish.
  SALVAGE EVERYTHING FROM _rubbish           - Restore all documents.
  INCINERATE "<id>" FROM _rubbish            - Permanently delete document.
  INCINERATE EVERYTHING FROM _rubbish        - Empty the trash bin.

2. READ & SEARCH (SCOOP Engine)
  FIND <bucket>                           - (Alias: SCOOP EVERYTHING FROM <bucket>)
  FIND <bucket> [Modifiers...]            - Native English document querying.
  
  [Modifiers - chainable in any order]
  ... WHERE <field> <op> <value>          - Evaluate expressions (<, >, =, AND, OR).
  ... WHOSE <field> IS <value>            - Exact field match filter.
  ... WITH <field1>, <field2>             - Native Joins (Alias: INCLUDE).
  ... SORTED BY <field> [DESC|ASC]        - Sort results (Alias: ARRANGED BY).
  ... LIMIT <n>                           - Restrict number of results.
  ... SHOW <field1>, <field2>             - Return specific fields (Alias: YIELD).
  ... MEANING "<text>"                    - AI Vector Semantic Search.
  ... MENTIONING "<text>"                 - Full Text Search.

3. GRAPH RELATIONS & TRAVERSAL (15D BONDS)
  BOND "<source_id>" TO "<target_id>" AS "<label>" - Create a directional relationship.
  FIND "<label>" OF "<source_id>"                  - Query direct relationships.
  TRACE "<label>" FROM "<source_id>"               - Traverse deep nested links.

4. AUTOMATION & TIME TRAVEL
  TIME TRAVEL <bucket> AS OF "<date>"     - Read historical state.
  SET CRON "<schedule>" DO <command>      - Register scheduled background tasks.
  SHOW CRON                               - List running background jobs.

5. ANALYTICS & AGGREGATION
  SCOOP THE TALLY OF <bucket>             - Total document count.
  SCOOP ONLY UNIQUE <field> FROM <bucket> - Returns distinct field values.
================================================================================"""
    print(help_text)
