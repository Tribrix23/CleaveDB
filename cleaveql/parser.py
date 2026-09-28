from typing import List, Any
from .tokens import Token, TokenType
from .ast import ScoopStmt, WhereClause, Predicate
import json

class ParserError(Exception):
    pass

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> List[Any]:
        stmts = []
        while not self.is_at_end():
            stmts.append(self.parse_statement())
        return stmts
        
    def parse_statement(self):
        if self.match(TokenType.SCOOP):
            return self.parse_scoop()
        raise ParserError(f"Unexpected token {self.peek().lexeme}")

    def parse_scoop(self) -> ScoopStmt:
        self.consume(TokenType.FROM, "Expected 'from' after 'scoop'")
        bucket = self.consume(TokenType.IDENTIFIER, "Expected bucket name").lexeme
        
        stmt = ScoopStmt(bucket=bucket, include=[])
        
        while not self.is_at_end() and self.peek().type not in (TokenType.EOF,):
            if self.match(TokenType.WHERE):
                stmt.where = self.parse_where()
            elif self.match(TokenType.MENTIONING):
                stmt.mentioning = self.consume(TokenType.STRING, "Expected string").lexeme
            elif self.match(TokenType.MEANING):
                stmt.meaning = self.consume(TokenType.STRING, "Expected string").lexeme
            elif self.match(TokenType.INCLUDE):
                stmt.include.append(self.consume(TokenType.IDENTIFIER, "Expected bond name").lexeme)
                while self.match(TokenType.COMMA):
                    stmt.include.append(self.consume(TokenType.IDENTIFIER, "Expected bond name").lexeme)
            elif self.match(TokenType.LIMIT):
                stmt.limit = int(self.consume(TokenType.NUMBER, "Expected integer limit").lexeme)
            else:
                break
                
        return stmt

    def parse_where(self) -> WhereClause:
        predicates = [self.parse_predicate()]
        while self.match(TokenType.AND):
            predicates.append(self.parse_predicate())
        return WhereClause(predicates)
        
    def parse_predicate(self) -> Predicate:
        field = self.consume(TokenType.IDENTIFIER, "Expected field name").lexeme
        op_tok = self.advance()
        if op_tok.type not in (TokenType.EQ, TokenType.NEQ, TokenType.GT, TokenType.GTE, TokenType.LT, TokenType.LTE):
            raise ParserError(f"Expected comparison operator, got {op_tok.lexeme}")
            
        val_tok = self.advance()
        val = val_tok.lexeme
        if val_tok.type == TokenType.NUMBER:
            val = float(val) if '.' in val else int(val)
            
        return Predicate(field, op_tok.lexeme, val)

    def match(self, *types) -> bool:
        for t in types:
            if self.check(t):
                self.advance()
                return True
        return False

    def check(self, type: TokenType) -> bool:
        if self.is_at_end():
            return False
        return self.peek().type == type

    def advance(self) -> Token:
        if not self.is_at_end():
            self.pos += 1
        return self.previous()

    def is_at_end(self) -> bool:
        return self.peek().type == TokenType.EOF

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def previous(self) -> Token:
        return self.tokens[self.pos - 1]

    def consume(self, type: TokenType, message: str) -> Token:
        if self.check(type):
            return self.advance()
        raise ParserError(f"{message} at line {self.peek().line}")
