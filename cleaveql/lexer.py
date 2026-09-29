from .tokens import Token, TokenType, KEYWORDS

class LexerError(Exception):
    pass

class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.length = len(source)
    
    def peek(self) -> str:
        if self.pos >= self.length:
            return '\0'
        return self.source[self.pos]
    
    def advance(self) -> str:
        char = self.peek()
        self.pos += 1
        if char == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return char

    def skip_whitespace_and_comments(self):
        while self.pos < self.length:
            c = self.peek()
            if c in ' \t\r\n':
                self.advance()
            elif c == '#':
                while self.peek() not in ('\n', '\0'):
                    self.advance()
            else:
                break

    def read_string(self, quote: str) -> Token:
        start_line = self.line
        start_column = self.column - 1 # -1 to include the quote
        value = []
        
        while self.pos < self.length:
            c = self.advance()
            if c == quote:
                return Token(TokenType.STRING, "".join(value), start_line, start_column, "".join(value))
            elif c == '\\':
                if self.pos >= self.length:
                    raise LexerError(f"Unterminated string starting at line {start_line}, column {start_column}")
                nc = self.advance()
                if nc == 'n': value.append('\n')
                elif nc == 't': value.append('\t')
                elif nc == '\\': value.append('\\')
                elif nc == '"': value.append('"')
                elif nc == "'": value.append("'")
                else:
                    value.append('\\' + nc)
            else:
                value.append(c)
                
        raise LexerError(f"Unterminated string starting at line {start_line}, column {start_column}")

    def read_number(self) -> Token:
        start_pos = self.pos - 1
        start_line = self.line
        start_column = self.column - 1
        
        has_dot = (self.source[start_pos] == '.')
        
        while self.pos < self.length:
            c = self.peek()
            if c.isdigit():
                self.advance()
            elif c == '.' and not has_dot:
                has_dot = True
                self.advance()
            else:
                break
                
        lexeme = self.source[start_pos:self.pos]
        if has_dot:
            return Token(TokenType.FLOAT, lexeme, start_line, start_column, float(lexeme))
        else:
            return Token(TokenType.INTEGER, lexeme, start_line, start_column, int(lexeme))

    def read_identifier_or_keyword(self) -> Token:
        start_pos = self.pos - 1
        start_line = self.line
        start_column = self.column - 1
        
        while self.pos < self.length:
            c = self.peek()
            # Identifiers can include '/' for bucket paths, e.g. shop/orders
            if c.isalnum() or c in '_/':
                self.advance()
            else:
                break
                
        lexeme = self.source[start_pos:self.pos]
        lower_lexeme = lexeme.lower()
        
        if lower_lexeme == 'max' and self.peek() not in ' \t\r\n\0' and not self.peek().isalnum():
            # Special case for max vs max_agg might need parser context, but here keywords handles max
            pass
            
        token_type = KEYWORDS.get(lower_lexeme, TokenType.IDENTIFIER)
        # Note: max maps to MAX. If MAX_AGG is needed, it might be parsed differently or keyword is 'max'
        return Token(token_type, lexeme, start_line, start_column, lexeme if token_type == TokenType.IDENTIFIER else None)

    def next_token(self) -> Token:
        self.skip_whitespace_and_comments()
        
        if self.pos >= self.length:
            return Token(TokenType.EOF, "", self.line, self.column)
            
        start_line = self.line
        start_column = self.column
        c = self.advance()
        
        if c in '"\'':
            return self.read_string(c)
            
        if c.isdigit():
            return self.read_number()
            
        if c.isalpha() or c == '_':
            return self.read_identifier_or_keyword()
            
        # Punctuation and operators
        if c == '.':
            if self.peek().isdigit():
                return self.read_number()
            return Token(TokenType.DOT, c, start_line, start_column)
        if c == '/': return Token(TokenType.SLASH, c, start_line, start_column)
        if c == ',': return Token(TokenType.COMMA, c, start_line, start_column)
        if c == '{': return Token(TokenType.LBRACE, c, start_line, start_column)
        if c == '}': return Token(TokenType.RBRACE, c, start_line, start_column)
        if c == '[': return Token(TokenType.LBRACKET, c, start_line, start_column)
        if c == ']': return Token(TokenType.RBRACKET, c, start_line, start_column)
        if c == ':': return Token(TokenType.COLON, c, start_line, start_column)
        if c == '(': return Token(TokenType.LPAREN, c, start_line, start_column)
        if c == ')': return Token(TokenType.RPAREN, c, start_line, start_column)
        if c == '*': return Token(TokenType.STAR, c, start_line, start_column)
        
        if c == '=': return Token(TokenType.EQ, c, start_line, start_column)
        if c == '!':
            if self.peek() == '=':
                self.advance()
                return Token(TokenType.NEQ, '!=', start_line, start_column)
            return Token(TokenType.UNKNOWN, c, start_line, start_column)
        if c == '<':
            if self.peek() == '=':
                self.advance()
                return Token(TokenType.LTE, '<=', start_line, start_column)
            return Token(TokenType.LT, c, start_line, start_column)
        if c == '>':
            if self.peek() == '=':
                self.advance()
                return Token(TokenType.GTE, '>=', start_line, start_column)
            return Token(TokenType.GT, c, start_line, start_column)
            
        return Token(TokenType.UNKNOWN, c, start_line, start_column)

    def tokenize(self) -> list[Token]:
        tokens = []
        while True:
            tok = self.next_token()
            tokens.append(tok)
            if tok.type == TokenType.EOF:
                break
        return tokens
