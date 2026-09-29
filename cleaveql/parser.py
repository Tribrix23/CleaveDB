from typing import List, Any, Optional
from .tokens import Token, TokenType
from .ast import *
import json

class ParseError(Exception):
    pass

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.current = 0
        self.errors = []

    def parse(self) -> List[Any]:
        statements = []
        while not self.is_at_end():
            try:
                stmt = self.statement()
                if stmt:
                    statements.append(stmt)
            except ParseError:
                self.synchronize()
        return statements

    def statement(self) -> Any:
        if self.match(TokenType.SCOOP):
            return self.scoop_stmt()
        if self.match(TokenType.COUNT):
            return self.count_stmt()
        if self.match(TokenType.DISTILL):
            return self.distill_stmt()
        if self.match(TokenType.FOLLOW):
            return self.follow_stmt()
        if self.match(TokenType.POUR):
            return self.pour_stmt()
        if self.match(TokenType.CHANGE):
            return self.change_stmt()
        if self.match(TokenType.DRAIN):
            return self.drain_stmt()
        if self.match(TokenType.SHAPE):
            return self.shape_stmt()
        if self.match(TokenType.BOND):
            return self.bond_stmt()
        if self.match(TokenType.INDEX):
            return self.index_stmt()
        if self.match(TokenType.HEAL):
            return self.heal_stmt()
        if self.match(TokenType.SHOW):
            return self.show_stmt()
        if self.match(TokenType.DESCRIBE):
            return self.describe_stmt()
        if self.match(TokenType.PEER):
            return self.peer_stmt()
        if self.match(TokenType.SUGGEST):
            return self.suggest_stmt()

        # If it doesn't match any statement, throw an error
        raise self.error(self.peek(), "Expected a statement.")

    def scoop_stmt(self) -> ScoopStmt:
        self.consume(TokenType.FROM, "Expected 'from' after 'scoop'.")
        bucket = self.consume_identifier("Expected bucket name.")
        
        where = None
        mentioning = None
        meaning = None
        include_list = []
        order_by = None
        
        while self.match(TokenType.WHERE, TokenType.WHOSE, TokenType.MEANING, TokenType.MENTIONING, TokenType.NEAR, TokenType.SINCE, TokenType.UNTIL, TokenType.ORDER, TokenType.INCLUDE):
            clause_type = self.previous().type
            if clause_type == TokenType.WHERE:
                where = self._parse_where()
            elif clause_type == TokenType.MENTIONING:
                tok = self.consume(TokenType.STRING, "Expected string after 'mentioning'.")
                mentioning = tok.value or tok.lexeme
            elif clause_type == TokenType.MEANING:
                tok = self.consume(TokenType.STRING, "Expected string after 'meaning'.")
                meaning = tok.value or tok.lexeme
            elif clause_type == TokenType.INCLUDE:
                include_list.append(self.consume_identifier("Expected bond/bucket name after 'include'."))
            elif clause_type == TokenType.ORDER:
                if self.match(TokenType.BY):
                    pass
                if self.match(TokenType.NEWEST, TokenType.OLDEST, TokenType.RELEVANCE):
                    order_by = self.previous().lexeme
                else:
                    order_by = self.consume_identifier("Expected sort order.")
            else:
                # WHOSE, NEAR, SINCE, UNTIL - consume expression tokens
                self.expression()
            
        limit = None
        if self.match(TokenType.LIMIT):
            limit_tok = self.consume(TokenType.INTEGER, "Expected integer for limit.")
            limit = limit_tok.value if limit_tok.value is not None else int(limit_tok.lexeme)
            
        return ScoopStmt(bucket=bucket, where=where, mentioning=mentioning, meaning=meaning, include=include_list, limit=limit, order_by=order_by)

    def scoop_clause(self, clause_type: TokenType) -> Any:
        if clause_type == TokenType.WHERE:
            return WhereClause(self.expression())
        elif clause_type == TokenType.WHOSE:
            return dict(clause_type="whose", expr=self.expression())
        elif clause_type == TokenType.MEANING:
            return dict(clause_type="meaning", expr=self.expression())
        elif clause_type == TokenType.MENTIONING:
            return dict(clause_type="mentioning", expr=self.expression())
        elif clause_type == TokenType.NEAR:
            return dict(clause_type="near", expr=self.expression())
        elif clause_type == TokenType.SINCE:
            return dict(clause_type="since", expr=self.expression())
        elif clause_type == TokenType.UNTIL:
            return dict(clause_type="until", expr=self.expression())
        elif clause_type == TokenType.ORDER:
            return dict(clause_type="order", expr=self.expression())
        elif clause_type == TokenType.INCLUDE:
            return dict(clause_type="include", expr=self.expression())
        raise self.error(self.peek(), "Invalid scoop clause.")

    def count_stmt(self) -> CountStmt:
        self.consume(TokenType.FROM, "Expected 'from' after 'count'.")
        bucket = self.consume_identifier("Expected bucket name.")
        
        clauses = []
        while self.match(TokenType.WHERE, TokenType.WHOSE, TokenType.MEANING, TokenType.MENTIONING, TokenType.NEAR, TokenType.SINCE, TokenType.UNTIL, TokenType.ORDER, TokenType.INCLUDE):
            clauses.append(self.scoop_clause(self.previous().type))
            
        where = None
        for c in clauses:
            if isinstance(c, WhereClause):
                where = c
        return CountStmt(bucket=bucket, where=where)

    def distill_stmt(self) -> DistillStmt:
        self.consume(TokenType.FROM, "Expected 'from' after 'distill'.")
        bucket = self.consume_identifier("Expected bucket name.")
        
        agg_function = self.consume_identifier("Expected aggregation function.")
        self.consume(TokenType.OF, "Expected 'of' after aggregation function.")
        field = self.consume_identifier("Expected field name.")
        
        clauses = []
        while self.match(TokenType.WHERE, TokenType.WHOSE, TokenType.MEANING, TokenType.MENTIONING, TokenType.NEAR, TokenType.SINCE, TokenType.UNTIL, TokenType.ORDER, TokenType.INCLUDE):
            clauses.append(self.scoop_clause(self.previous().type))
            
        return DistillStmt(bucket=bucket, agg_function=agg_function, field=field)

    def follow_stmt(self) -> FollowStmt:
        doc_key = self.consume_doc_id("Expected document key.")
        
        bond = None
        if self.match(TokenType.THROUGH):
            bond = self.consume_identifier("Expected bond name.")
            
        direction = None
        if self.match(TokenType.DIRECTION):
            if self.match(TokenType.OUT, TokenType.IN, TokenType.BOTH):
                direction = self.previous().lexeme
            else:
                raise self.error(self.peek(), "Expected 'out', 'in', or 'both' for direction.")
                
        depth = None
        if self.match(TokenType.DEPTH):
            depth = self.consume(TokenType.INTEGER, "Expected integer for depth.").value
            
        limit = None
        if self.match(TokenType.LIMIT):
            limit = self.consume(TokenType.INTEGER, "Expected integer for limit.").value
            
        return FollowStmt(doc_key=doc_key, bond_name=bond, direction=direction, depth=depth, limit=limit)

    def pour_stmt(self) -> Any:
        if self.match(TokenType.INTO):
            bucket = self.consume_identifier("Expected bucket name.")
            doc_id = self.consume_doc_id("Expected document ID.")
            data = self.consume_json("Expected JSON object.")
            return PourStmt(bucket=bucket, doc_id=doc_id, json_body=data)
        elif self.match(TokenType.MANY):
            self.consume(TokenType.INTO, "Expected 'into' after 'pour many'.")
            bucket = self.consume_identifier("Expected bucket name.")
            data = self.consume_json("Expected JSON array.")
            return PourManyStmt(bucket=bucket, json_array=data)
        else:
            raise self.error(self.peek(), "Expected 'into' or 'many' after 'pour'.")

    def change_stmt(self) -> ChangeStmt:
        bucket = self.consume_identifier("Expected bucket name.")
        doc_id = self.consume_doc_id("Expected document ID.")
        self.consume(TokenType.SET, "Expected 'set' after document ID.")
        
        updates = []
        while True:
            field = self.consume_identifier("Expected field name.")
            self.consume(TokenType.TO, "Expected 'to' after field name.")
            value = self.consume_value("Expected value.")
            updates.append((field, value))
            
            if not self.match(TokenType.COMMA):
                break
                
        return ChangeStmt(bucket=bucket, doc_id=doc_id, assignments=updates)

    def drain_stmt(self) -> Any:
        bucket = self.consume_identifier("Expected bucket name.")
        
        if self.match(TokenType.WHERE):
            where = self._parse_where()
            return DrainStmt(bucket=bucket, where=where)
        elif self.match(TokenType.BEFORE):
            datetime_val = self.consume(TokenType.STRING, "Expected datetime string.").value
            return DrainStmt(bucket=bucket, before=datetime_val)
        else:
            doc_id = self.consume_doc_id("Expected document ID.")
            return DrainStmt(bucket=bucket, doc_id=doc_id)

    def shape_stmt(self) -> Any:
        if self.match(TokenType.BUCKET):
            path = self.consume_identifier("Expected bucket path.")
            compression = None
            ttl = None
            max_documents = None
            versioned = False
            while self.match(TokenType.COMPRESSION, TokenType.TTL, TokenType.MAX, TokenType.VERSIONED):
                prop_name = self.previous().type
                if prop_name == TokenType.COMPRESSION:
                    compression = str(self.consume_value("Expected compression value."))
                elif prop_name == TokenType.TTL:
                    ttl = str(self.consume_value("Expected TTL value."))
                elif prop_name == TokenType.MAX:
                    if self.match(TokenType.DOCUMENTS):
                        pass
                    max_documents = self.consume_value("Expected max documents value.")
                elif prop_name == TokenType.VERSIONED:
                    versioned = True
            return ShapeBucketStmt(path=path, compression=compression, ttl=ttl, max_documents=max_documents, versioned=versioned)
            
        elif self.match(TokenType.PROJECTION):
            path = self.consume_identifier("Expected projection path.")
            self.consume(TokenType.FROM, "Expected 'from' after projection path.")
            bucket = self.consume_identifier("Expected bucket name.")
            where = None
            if self.match(TokenType.WHERE):
                where = self.expression()
            return ShapeProjectionStmt(path=path, from_bucket=bucket, where=where)
            
        elif self.match(TokenType.FLOW):
            self.consume(TokenType.FROM, "Expected 'from' after 'shape flow'.")
            source = self.consume_identifier("Expected source bucket.")
            self.consume(TokenType.TO, "Expected 'to' after source bucket.")
            dest = self.consume_identifier("Expected destination bucket.")
            self.consume(TokenType.WHEN, "Expected 'when' after destination bucket.")
            when = self.expression()
            
            action = None
            if self.match(TokenType.ACTION):
                if self.match(TokenType.COPY, TokenType.MOVE):
                    action = self.previous().lexeme
                else:
                    raise self.error(self.peek(), "Expected 'copy' or 'move' for action.")
            return FlowStmt(from_bucket=source, to_bucket=dest, when=when, action=action or '')
            
        else:
            raise self.error(self.peek(), "Expected 'bucket', 'projection', or 'flow' after 'shape'.")

    def bond_stmt(self) -> BondStmt:
        name = self.consume_identifier("Expected bond name.")
        self.consume(TokenType.FROM, "Expected 'from' after bond name.")
        
        # qualified field
        source_bucket = self.consume_identifier("Expected bucket name for qualified field.")
        self.consume(TokenType.DOT, "Expected '.' in qualified field.")
        source_field = self.consume_identifier("Expected field name in qualified field.")
        qualified_field = f"{source_bucket}.{source_field}"
        
        self.consume(TokenType.TO, "Expected 'to' after qualified field.")
        dest_bucket = self.consume_identifier("Expected target bucket.")
        
        strength = None
        if self.match(TokenType.STRENGTH):
            if self.match(TokenType.SOFT, TokenType.FIRM, TokenType.STRICT):
                strength = self.previous().lexeme
            else:
                raise self.error(self.peek(), "Expected 'soft', 'firm', or 'strict'.")
                
        on_delete = None
        if self.match(TokenType.ON):
            self.consume(TokenType.DELETE, "Expected 'delete' after 'on'.")
            if self.match(TokenType.KEEP, TokenType.RESTRICT, TokenType.CASCADE):
                on_delete = self.previous().lexeme
            else:
                raise self.error(self.peek(), "Expected 'keep', 'restrict', or 'cascade'.")
                
        cardinality = None
        if self.match(TokenType.CARDINALITY):
            if self.match(TokenType.ONE, TokenType.MANY):
                cardinality = self.previous().lexeme
            else:
                raise self.error(self.peek(), "Expected 'one' or 'many'.")
                
        return BondStmt(name=name, from_field=qualified_field, to_bucket=dest_bucket, strength=strength or '', on_delete=on_delete or '', cardinality=cardinality or '')

    def index_stmt(self) -> IndexStmt:
        bucket = self.consume_identifier("Expected bucket name.")
        self.consume(TokenType.ON, "Expected 'on' after bucket name.")
        self.consume(TokenType.LPAREN, "Expected '(' after 'on'.")
        
        fields = []
        while True:
            fields.append(self.consume_identifier("Expected field name."))
            if not self.match(TokenType.COMMA):
                break
                
        self.consume(TokenType.RPAREN, "Expected ')' after fields.")
        return IndexStmt(bucket=bucket, fields=fields)

    def heal_stmt(self) -> HealStmt:
        if self.match(TokenType.BONDS, TokenType.INDEXES, TokenType.ALL):
            return HealStmt(target=self.previous().lexeme)
        raise self.error(self.peek(), "Expected 'bonds', 'indexes', or 'all' after 'heal'.")

    def show_stmt(self) -> ShowStmt:
        if self.match(TokenType.BUCKETS, TokenType.BONDS, TokenType.INDEXES, TokenType.STATS):
            return ShowStmt(target=self.previous().lexeme)
        raise self.error(self.peek(), "Expected 'buckets', 'bonds', 'indexes', or 'stats' after 'show'.")

    def describe_stmt(self) -> DescribeStmt:
        bucket = self.consume_identifier("Expected bucket name.")
        return DescribeStmt(bucket=bucket)

    def peer_stmt(self) -> PeerStmt:
        self.consume(TokenType.INTO, "Expected 'into' after 'peer'.")
        if self.match(TokenType.ATTENTION):
            return PeerStmt(attention=True)
        else:
            return PeerStmt(target_stmt=self.statement())

    def suggest_stmt(self) -> SuggestStmt:
        self.consume(TokenType.BONDS, "Expected 'bonds' after 'suggest'.")
        return SuggestStmt(target="bonds")

    def _parse_where(self) -> WhereClause:
        """Parse a WHERE clause with predicates connected by AND/OR."""
        predicates = []
        connectives = []
        predicates.append(self._parse_predicate())
        while self.match(TokenType.AND, TokenType.OR):
            connectives.append(self.previous().lexeme)
            predicates.append(self._parse_predicate())
        return WhereClause(predicates=predicates, connectives=connectives)

    def _parse_predicate(self) -> 'Predicate':
        """Parse field op value."""
        field = self.consume_identifier("Expected field name in predicate.")
        if self.match(TokenType.GTE):
            op = ">="
        elif self.match(TokenType.LTE):
            op = "<="
        elif self.match(TokenType.NEQ):
            op = "!="
        elif self.match(TokenType.GT):
            op = ">"
        elif self.match(TokenType.LT):
            op = "<"
        elif self.match(TokenType.EQ):
            op = "="
        else:
            raise self.error(self.peek(), "Expected comparison operator.")
        value = self.consume_value("Expected value in predicate.")
        return Predicate(field=field, op=op, value=value)

    # Helpers
    def match(self, *types: TokenType) -> bool:
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
            self.current += 1
        return self.previous()

    def is_at_end(self) -> bool:
        return self.peek().type == TokenType.EOF

    def peek(self) -> Token:
        return self.tokens[self.current]

    def previous(self) -> Token:
        return self.tokens[self.current - 1]

    def consume(self, type: TokenType, message: str) -> Token:
        if self.check(type):
            return self.advance()
        raise self.error(self.peek(), message)

    def consume_identifier(self, message: str) -> str:
        # Accept IDENTIFIER or any keyword token as a field/bucket name
        # (keywords like 'total', 'status', 'name' can be field names in context)
        if self.check(TokenType.IDENTIFIER):
            return self.advance().lexeme
        # Allow keywords to be used as identifiers
        if not self.is_at_end() and self.peek().type not in (
            TokenType.EOF, TokenType.EQ, TokenType.NEQ, TokenType.GT, TokenType.GTE,
            TokenType.LT, TokenType.LTE, TokenType.COMMA, TokenType.LPAREN, TokenType.RPAREN,
            TokenType.LBRACE, TokenType.RBRACE, TokenType.LBRACKET, TokenType.RBRACKET,
            TokenType.INTEGER, TokenType.FLOAT, TokenType.STRING,
        ):
            return self.advance().lexeme
        raise self.error(self.peek(), message)
        
    def consume_doc_id(self, message: str) -> str:
        if self.match(TokenType.IDENTIFIER, TokenType.STRING):
            return self.previous().value or self.previous().lexeme
        raise self.error(self.peek(), message)
        
    def consume_json(self, message: str) -> Any:
        # Try JSON_LITERAL first (if lexer supports it), then STRING, then inline brace
        if hasattr(TokenType, 'JSON_LITERAL') and self.match(TokenType.JSON_LITERAL):
            val = self.previous().value
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    pass
            return val
        if self.match(TokenType.STRING):
            # The token value should already be parsed JSON, or we might need to parse it
            val = self.previous().value
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    pass
            return val
        # Handle inline JSON by collecting raw text from braces/brackets
        if self.check(TokenType.LBRACE) or self.check(TokenType.LBRACKET):
            open_tok = TokenType.LBRACE if self.check(TokenType.LBRACE) else TokenType.LBRACKET
            close_tok = TokenType.RBRACE if open_tok == TokenType.LBRACE else TokenType.RBRACKET
            depth = 0
            parts = []
            while not self.is_at_end():
                if self.check(open_tok):
                    depth += 1
                elif self.check(close_tok):
                    depth -= 1
                    if depth == 0:
                        parts.append(self.advance().lexeme)
                        break
                tok = self.advance()
                # Re-add quotes for string tokens since the lexer strips them
                if tok.type == TokenType.STRING:
                    # Escape any internal quotes
                    escaped = tok.value.replace('\\', '\\\\').replace('"', '\\"') if isinstance(tok.value, str) else str(tok.value)
                    parts.append(f'"{escaped}"')
                elif tok.type == TokenType.IDENTIFIER:
                    # Identifiers in JSON context are typically keys — quote them
                    parts.append(f'"{tok.lexeme}"')
                else:
                    parts.append(tok.lexeme)
            json_str = "".join(parts)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                return json_str
        raise self.error(self.peek(), message)
        
    def consume_value(self, message: str) -> Any:
        if self.match(TokenType.INTEGER, TokenType.FLOAT, TokenType.STRING):
            return self.previous().value
        if self.match(TokenType.IDENTIFIER):
            lex = self.previous().lexeme.lower()
            if lex == 'true': return True
            if lex == 'false': return False
            if lex == 'null': return None
            return self.previous().lexeme
        raise self.error(self.peek(), message)

    def expression(self) -> Any:
        # Placeholder for expression parsing logic since EBNF didn't detail it
        # Just consume tokens until a keyword or end of statement
        expr_tokens = []
        while not self.is_at_end() and not self.peek().type in (
            TokenType.WHERE, TokenType.WHOSE, TokenType.MEANING, 
            TokenType.MENTIONING, TokenType.NEAR, TokenType.SINCE, 
            TokenType.UNTIL, TokenType.ORDER, TokenType.INCLUDE, TokenType.LIMIT,
            TokenType.EOF):
            expr_tokens.append(self.advance())
        return expr_tokens

    def error(self, token: Token, message: str) -> ParseError:
        self.errors.append(f"Error at '{token.lexeme}': {message}")
        return ParseError()

    def synchronize(self):
        self.advance()
        while not self.is_at_end():
            # If we find a keyword that starts a statement, stop synchronizing
            if self.peek().type in (
                TokenType.SCOOP, TokenType.COUNT, TokenType.DISTILL,
                TokenType.FOLLOW, TokenType.POUR, TokenType.CHANGE,
                TokenType.DRAIN, TokenType.SHAPE, TokenType.BOND,
                TokenType.INDEX, TokenType.HEAL, TokenType.SHOW,
                TokenType.DESCRIBE, TokenType.PEER, TokenType.SUGGEST
            ):
                return
            self.advance()
