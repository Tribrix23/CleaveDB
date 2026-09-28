import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from cleaveql.lexer import Lexer
from cleaveql.parser import Parser

query = 'scoop from shop/orders where total >= 100 mentioning "espresso" include customer limit 10'

lexer = Lexer(query)
tokens = lexer.tokenize()
print("Tokens:")
for t in tokens:
    print(f"  {t.type.name}: {t.lexeme}")

parser = Parser(tokens)
ast = parser.parse()
print("\nAST:")
for node in ast:
    print(f"  {node}")

print("\nMilestone 4 parsing successful!")
