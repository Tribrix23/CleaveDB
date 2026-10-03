import sys
from .lexer import Lexer
from .parser import Parser, ParseError
from .semantic import SemanticAnalyzer
from .interpreter import Interpreter
from .formatter import Formatter

def start_repl(engine=None):
    print("CleaveDB 3.9.0 REPL")
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
  CleaveDB 3.9.0 Manual (CleaveQL) - Complete Reference
================================================================================

 MUTATIONS: POUR INTO, POUR MANY, CHANGE, DRAIN, SALVAGE, INCINERATE
 QUERIES:   FIND (10 modes: EVERYTHING, FIRST, LAST, TALLY, HIGHEST,
            LOWEST, UNIQUE, TOTAL, RELATED, CHAIN)
 MODIFIERS: WHERE, WHOSE, MENTIONING, MEANING, MATCHING, WITH/INCLUDE,
            SHOW/YIELD, ARRANGED BY, LIMIT, GROUPED BY, AS OF, CANDIDATE
 GRAPH:     LINK/BOND (MUTUAL, CASCADE, EXCLUSIVELY, CONFIDENCE, AFFINITY,
            EXPIRING IN, CONDITION, THROUGH, ANY), SEVER/UNLINK, FOLLOW
 SECURITY:  ENFORCE SECURITY, MASK, DROP SECURITY, SET, AUTHENTICATE AS
 ANALYTICS: TALLY, HIGHEST, LOWEST, UNIQUE, TOTAL, DISTILL
 INFRA:     SHAPE BUCKET/PROJECTION/FLOW, INDEX, EVERY...DO
 DIAG:      SHOW BUCKETS/BONDS/INDEXES/STATS, DESCRIBE, HEAL, PEER, SUGGEST

 Type 'help' in the CLI shell for the full detailed manual.
================================================================================""" 
    print(help_text)
