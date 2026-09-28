import re
from typing import List
from .tokens import Token, TokenType, KEYWORDS

class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        while self.pos < len(self.source):
            c = self.source[self.pos]
            
            if c.isspace():
                if c == '\n':
                    self.line += 1
                    self.col = 1
                else:
                    self.col += 1
                self.pos += 1
                continue
                
            if c.isalpha() or c == '_' or c == '/':
                self._identifier()
            elif c.isdigit() or (c == '-' and self.pos + 1 < len(self.source) and self.source[self.pos+1].isdigit()):
                self._number()
            elif c == '"':
                self._string()
            elif c == '{' or c == '[':
                self._json()
            else:
                self._operator()
                
        self.tokens.append(Token(TokenType.EOF, "", self.line, self.col))
        return self.tokens

    def _identifier(self):
        start = self.pos
        while self.pos < len(self.source) and (self.source[self.pos].isalnum() or self.source[self.pos] in '_/-.'):
            self.pos += 1
            self.col += 1
        lexeme = self.source[start:self.pos]
        tok_type = KEYWORDS.get(lexeme.lower(), TokenType.IDENTIFIER)
        self.tokens.append(Token(tok_type, lexeme, self.line, self.col - len(lexeme)))

    def _number(self):
        start = self.pos
        if self.source[self.pos] == '-':
            self.pos += 1
            self.col += 1
        while self.pos < len(self.source) and (self.source[self.pos].isdigit() or self.source[self.pos] == '.'):
            self.pos += 1
            self.col += 1
        lexeme = self.source[start:self.pos]
        self.tokens.append(Token(TokenType.NUMBER, lexeme, self.line, self.col - len(lexeme)))

    def _string(self):
        start = self.pos
        self.pos += 1
        self.col += 1
        while self.pos < len(self.source) and self.source[self.pos] != '"':
            self.pos += 1
            self.col += 1
        self.pos += 1 # consume closing quote
        self.col += 1
        lexeme = self.source[start+1:self.pos-1]
        self.tokens.append(Token(TokenType.STRING, lexeme, self.line, self.col - len(lexeme) - 2))

    def _json(self):
        # A simple stack-based json extractor for "{...}" or "[...]"
        start = self.pos
        stack = []
        while self.pos < len(self.source):
            c = self.source[self.pos]
            if c in '{[':
                stack.append(c)
            elif c in '}]':
                if stack:
                    stack.pop()
            self.pos += 1
            self.col += 1
            if not stack:
                break
        lexeme = self.source[start:self.pos]
        self.tokens.append(Token(TokenType.JSON_LITERAL, lexeme, self.line, self.col - len(lexeme)))

    def _operator(self):
        c = self.source[self.pos]
        nxt = self.source[self.pos+1] if self.pos + 1 < len(self.source) else ' '
        
        op_map = {
            '=': TokenType.EQ,
            '(': TokenType.LPAREN,
            ')': TokenType.RPAREN,
            ',': TokenType.COMMA,
        }
        
        if c == '!' and nxt == '=':
            self.tokens.append(Token(TokenType.NEQ, "!=", self.line, self.col))
            self.pos += 2
            self.col += 2
            return
        elif c == '>' and nxt == '=':
            self.tokens.append(Token(TokenType.GTE, ">=", self.line, self.col))
            self.pos += 2
            self.col += 2
            return
        elif c == '<' and nxt == '=':
            self.tokens.append(Token(TokenType.LTE, "<=", self.line, self.col))
            self.pos += 2
            self.col += 2
            return
        elif c == '>':
            self.tokens.append(Token(TokenType.GT, ">", self.line, self.col))
            self.pos += 1
            self.col += 1
            return
        elif c == '<':
            self.tokens.append(Token(TokenType.LT, "<", self.line, self.col))
            self.pos += 1
            self.col += 1
            return
            
        if c in op_map:
            self.tokens.append(Token(op_map[c], c, self.line, self.col))
        else:
            self.tokens.append(Token(TokenType.UNKNOWN, c, self.line, self.col))
            
        self.pos += 1
        self.col += 1
