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
            stmt = self.statement()
            if stmt:
                statements.append(stmt)
        return statements

    def statement(self) -> Any:
        if self.match(TokenType.SCOOP):
            return self.scoop_stmt()
        if self.match(TokenType.COUNT):
            return self.scoop_stmt() # Fallback for legacy count
        if self.match(TokenType.DISTILL):
            return self.distill_stmt()
        if self.match(TokenType.FOLLOW):
            return self.follow_stmt()
        if self.match(TokenType.POUR):
            return self.pour_stmt()
        if self.match(TokenType.SET):
            return self.set_context_stmt()
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
        if self.match(TokenType.EVERY):
            return self.cron_stmt()

        # If it doesn't match any statement, throw an error
        raise self.error(self.peek(), "Expected a statement.")

    def scoop_stmt(self) -> ScoopStmt:
        mode = "EVERYTHING"
        mode_count = None
        yield_fields = []
        related_label = None
        related_source = None
        target_field = None
        
        # Check for SCOOP RELATED "label" FROM "doc"
        if self.match(TokenType.RELATED):
            mode = "RELATED"
            related_label = self.consume_string("Expected relationship label (string).")
            self.consume(TokenType.FROM, "Expected 'from'.")
            related_source = self.consume_string("Expected source document ID.")
            stmt = ScoopStmt(line=self.previous().line, column=self.previous().column)
            stmt.mode = mode
            stmt.related_label = related_label
            stmt.related_source = related_source
            return stmt
            
        if self.match(TokenType.ONLY):
            self.consume(TokenType.UNIQUE, "Expected 'unique'.")
            mode = "UNIQUE"
            target_field = self.consume_identifier("Expected field for unique.")
            self.consume(TokenType.FROM, "Expected 'from'.")
        elif self.match(TokenType.THE):
            if self.match(TokenType.FIRST):
                mode = "FIRST"
                mode_count = self.consume(TokenType.INTEGER, "Expected number after 'first'.").value
                self.consume(TokenType.FROM, "Expected 'from'.")
            elif self.match(TokenType.LAST):
                mode = "LAST"
                mode_count = self.consume(TokenType.INTEGER, "Expected number after 'last'.").value
                self.consume(TokenType.FROM, "Expected 'from'.")
            elif self.match(TokenType.TALLY):
                self.consume(TokenType.OF, "Expected 'of'.")
                mode = "TALLY"
                # SCOOP THE TALLY OF users -> bucket comes next
            elif self.match(TokenType.TOTAL):
                mode = "TOTAL"
                target_field = self.consume_identifier("Expected field to sum.")
                self.consume(TokenType.FROM, "Expected 'from'.")
            elif self.match(TokenType.HIGHEST):
                mode = "HIGHEST"
                mode_count = self.consume(TokenType.INTEGER, "Expected limit count.").value
                target_field = self.consume_identifier("Expected sort field.")
                self.consume(TokenType.FROM, "Expected 'from'.")
            elif self.match(TokenType.LOWEST):
                mode = "LOWEST"
                mode_count = self.consume(TokenType.INTEGER, "Expected limit count.").value
                target_field = self.consume_identifier("Expected sort field.")
                self.consume(TokenType.FROM, "Expected 'from'.")
            else:
                # CHAIN relational lookup!
                rel_chain = []
                rel_chain.append(self.consume_identifier("Expected relationship label"))
                self.consume(TokenType.OF, "Expected 'of'")
                while self.match(TokenType.THE):
                    rel_chain.append(self.consume_identifier("Expected relationship label"))
                    self.consume(TokenType.OF, "Expected 'of'")
                
                bucket = self.consume_identifier("Expected target bucket for chain")
                doc_id = self.consume_string("Expected doc id")
                
                stmt = ScoopStmt(line=self.previous().line, column=self.previous().column)
                stmt.mode = "CHAIN"
                stmt.chain_labels = rel_chain
                stmt.chain_source = f"{bucket}:{doc_id}"
                return stmt
        elif self.match(TokenType.EVERYTHING):
            self.consume(TokenType.FROM, "Expected 'from' after scoop modifiers.")
        else:
            if not self.check(TokenType.IDENTIFIER):
                self.consume(TokenType.FROM, "Expected 'from'.")
            elif self.peek().lexeme.lower() == 'from':
                self.consume(TokenType.FROM, "Expected 'from'.")
        
        bucket = self.consume_identifier("Expected bucket name.")
        
        where = None
        if self.match(TokenType.WHERE):
            where = self._parse_where()
            
        whose_field = None
        whose_value = None
        if self.match(TokenType.WHOSE):
            whose_field = self.consume_identifier("Expected field after 'whose'.")
            self.consume(TokenType.IS, "Expected 'is'.")
            whose_value = self.consume_value("Expected value.")
            
        mentioning = None
        if self.match(TokenType.MENTIONING):
            mentioning = self.consume_string("Expected search string after mentioning.")
            
        meaning = None
        if self.match(TokenType.MEANING):
            meaning = self.consume_string("Expected search string after meaning.")
            
        matching = None
        if self.match(TokenType.MATCHING):
            match_str = self.consume_string("Expected JSON object string after matching.")
            import json
            matching = json.loads(match_str)
            
        include = []
        if self.match(TokenType.INCLUDE):
            include.append(self.consume_identifier("Expected field to include."))
            while self.match(TokenType.COMMA):
                include.append(self.consume_identifier("Expected field after comma."))
                
        arrange_field = None
        arrange_dir = "ASC"
        if self.match(TokenType.ARRANGED):
            self.consume(TokenType.BY, "Expected 'by' after arranged")
            arrange_field = self.consume_identifier("Expected field")
            if self.match(TokenType.GOING):
                if self.match(TokenType.UP): arrange_dir = "ASC"
                elif self.match(TokenType.DOWN): arrange_dir = "DESC"

        limit = None
        if self.match(TokenType.LIMIT):
            limit = self.consume(TokenType.INTEGER, "Expected number after limit.").value
            
        group_by = None
        if self.match(TokenType.GROUPED):
            self.consume(TokenType.BY, "Expected 'by' after 'grouped'.")
            group_by = self.consume_identifier("Expected field for group by.")
            
        stmt = ScoopStmt(line=self.previous().line, column=self.previous().column)
        stmt.bucket = bucket
        stmt.where = where
        stmt.mentioning = mentioning
        stmt.meaning = meaning
        stmt.include = include
        stmt.matching = matching
        stmt.yield_fields = yield_fields
        stmt.target_field = target_field
        stmt.group_by = group_by
        stmt.mode = mode
        stmt.mode_count = mode_count
        stmt.whose_field = whose_field
        stmt.whose_value = whose_value
        stmt.limit = limit
        stmt.arrange_field = arrange_field
        stmt.arrange_dir = arrange_dir
        
        as_of = None
        if self.match(TokenType.AS):
            self.consume(TokenType.OF, "Expected 'of' after 'as'.")
            if self.match(TokenType.STRING):
                as_of = self.previous().value
            else:
                as_of = self.consume_identifier("Expected 'yesterday' or timestamp.")
        stmt.as_of = as_of
        
        return stmt

    def distill_stmt(self) -> DistillStmt:
        self.consume(TokenType.FROM, "Expected 'from' after 'distill'.")
        bucket = self.consume_identifier("Expected bucket name.")
        
        agg_function = self.consume_identifier("Expected aggregation function.")
        self.consume(TokenType.OF, "Expected 'of' after aggregation function.")
        field = self.consume_identifier("Expected field name.")
        
        clauses = []
        while self.match(TokenType.WHERE, TokenType.WHOSE, TokenType.MEANING, TokenType.MENTIONING, TokenType.NEAR, TokenType.SINCE, TokenType.UNTIL, TokenType.ORDER, TokenType.INCLUDE, TokenType.MATCHING, TokenType.YIELD):
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
            
        arrange_field = None
        arrange_dir = "ASC"
        if self.match(TokenType.ARRANGED):
            self.consume(TokenType.BY, "Expected 'by' after arranged")
            arrange_field = self.consume_identifier("Expected field")
            if self.match(TokenType.GOING):
                if self.match(TokenType.UP): arrange_dir = "ASC"
                elif self.match(TokenType.DOWN): arrange_dir = "DESC"

        limit = None
        if self.match(TokenType.LIMIT):
            limit = self.consume(TokenType.INTEGER, "Expected integer for limit.").value
            
        return FollowStmt(doc_key=doc_key, bond_name=bond, direction=direction, depth=depth, limit=limit)

    def pour_stmt(self) -> Any:
        if self.match(TokenType.STRING):
            # Try to handle POUR json INSIDE bucket "doc_id" AT field
            val = self.previous().value
            import json
            try:
                data = json.loads(val) if isinstance(val, str) else val
            except:
                data = val
                
            # If the next token is IDENTIFIER and lexeme is "inside"
            if self.match(TokenType.IDENTIFIER) and self.previous().lexeme.lower() == "inside":
                bucket = self.consume_identifier("Expected bucket name.")
                doc_id = self.consume_doc_id("Expected document ID.")
                if self.match(TokenType.IDENTIFIER) and self.previous().lexeme.lower() == "at":
                    field = self.consume_identifier("Expected field path.")
                    # Return it as a ChangeStmt!
                    return ChangeStmt(bucket=bucket, doc_id=doc_id, assignments=[(field, data)])
        
        if self.match(TokenType.INTO):
            bucket = self.consume_identifier("Expected bucket name.")
            
            # Support auto-generated RANDOM IDs natively
            if self.match(TokenType.RANDOM):
                doc_id = None
            else:
                doc_id = self.consume_doc_id("Expected document ID or RANDOM.")
                
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
            
        elif self.match(TokenType.POLICY):
            name = self.consume_identifier("Expected policy name.")
            self.consume(TokenType.ON, "Expected 'on' after policy name.")
            bucket = self.consume_identifier("Expected bucket name.")
            self.consume(TokenType.FOR, "Expected 'for' after bucket name.")
            
            action = 'all'
            if self.match(TokenType.READ, TokenType.WRITE, TokenType.ALL):
                action = self.previous().lexeme.lower()
            else:
                raise self.error(self.peek(), "Expected 'read', 'write', or 'all'.")
                
            self.consume(TokenType.USING, "Expected 'using' after action.")
            condition = self.expression()
            
            from .ast import PolicyStmt
            return PolicyStmt(name=name, bucket=bucket, action=action, condition=condition)

        elif self.match(TokenType.MASK):
            field = self.consume_identifier("Expected field name to mask.")
            self.consume(TokenType.ON, "Expected 'on' after field name.")
            bucket = self.consume_identifier("Expected bucket name.")
            self.consume(TokenType.USING, "Expected 'using' after bucket name.")
            condition = self.expression()
            from .ast import MaskStmt
            return MaskStmt(field=field, bucket=bucket, condition=condition)

            
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
        # We matched BOND in statement()
        source_gid = self.consume_string("Expected source document ID.")
        self.consume(TokenType.TO, "Expected 'to'.")
        
        # Support Polymorphic ANY, but resolve gracefully to string for now
        if self.match(TokenType.ANY):
            self.consume(TokenType.LPAREN, "Expected '(' after ANY.")
            target_gid = "ANY(" + self.consume_identifier("Expected ANY arguments.") + ")"
            while self.match(TokenType.COMMA):
                target_gid = target_gid[:-1] + "," + self.consume_identifier("Expected ANY args.") + ")"
            self.consume(TokenType.RPAREN, "Expected ')'.")
        else:
            target_gid = self.consume_string("Expected target document ID.")
            
        mutual = False
        if self.match(TokenType.AS):
            if self.match(TokenType.MUTUAL):
                mutual = True
            label = self.consume_string("Expected relationship label.")
        else:
            label = "linked"
            
        stmt = BondStmt(line=self.previous().line, column=self.previous().column)
        stmt.source_gid = source_gid
        stmt.target_gid = target_gid
        stmt.label = label
        stmt.mutual = mutual
        
        # Modifier Loop
        while not self.is_at_end() and self.peek().type not in [TokenType.SCOOP, TokenType.POUR, TokenType.EOF, TokenType.CHANGE, TokenType.BOND]:
            if self.match(TokenType.ONLY):
                self.consume(TokenType.WHEN, "Expected 'when'.")
                stmt.condition_field = self.consume_identifier("Expected field.")
                self.consume(TokenType.IS, "Expected 'is'.")
                stmt.condition_value = self.consume_value("Expected value.")
            elif self.match(TokenType.WITH):
                if self.match(TokenType.AFFINITY):
                    stmt.affinity = float(self.consume(TokenType.FLOAT, "Expected affinity.").value)
                elif self.match(TokenType.CONFIDENCE):
                    stmt.confidence = float(self.consume(TokenType.FLOAT, "Expected confidence.").value)
            elif self.match(TokenType.THROUGH):
                stmt.through = self.consume_identifier("Expected through node.")
            elif self.match(TokenType.ON):
                self.consume(TokenType.DELETE, "Expected 'delete'.")
                self.consume(TokenType.CASCADE, "Expected 'cascade'.")
                stmt.cascade = True
            elif self.match(TokenType.EXCLUSIVELY):
                stmt.exclusive = True
            elif self.match(TokenType.EXPIRING):
                self.consume(TokenType.IN, "Expected 'in'.")
                num = self.consume(TokenType.INTEGER, "Expected number.").value
                if self.match(TokenType.HOUR, TokenType.HOURS):
                    stmt.expires_at = num * 3600
                elif self.match(TokenType.MINUTE, TokenType.MINUTES):
                    stmt.expires_at = num * 60
                else:
                    self.consume_identifier("Time unit.")
                    stmt.expires_at = num
            else:
                break
                
        return stmt

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

    def consume_string(self, message: str) -> str:
        return str(self.consume(TokenType.STRING, message).value)
        
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
        if self.match(TokenType.LPAREN):
            if self.match(TokenType.SCOOP):
                stmt = self.scoop_stmt()
                self.consume(TokenType.RPAREN, "Expected ')' after sub-scoop.")
                return {"_type": "sub_scoop", "stmt": stmt}
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

    def set_context_stmt(self):
        key = self.consume_identifier("Expected context key.")
        self.consume(TokenType.EQ, "Expected '=' after key.")
        value = self.consume_value("Expected value.")
        from .ast import SetContextStmt
        return SetContextStmt(key=key, value=value)


    def cron_stmt(self) -> CronStmt:
        interval = 0
        if self.match(TokenType.DAY):
            self.consume(TokenType.AT, "Expected 'at' after 'day'.")
            self.consume(TokenType.MIDNIGHT, "Expected 'midnight' after 'at'.")
            interval = 86400
        else:
            num = self.consume(TokenType.INTEGER, "Expected interval number.").value
            if self.match(TokenType.SECOND, TokenType.SECONDS):
                interval = num
            elif self.match(TokenType.MINUTE, TokenType.MINUTES):
                interval = num * 60
            elif self.match(TokenType.HOUR, TokenType.HOURS):
                interval = num * 3600
            else:
                raise self.error(self.peek(), "Expected time unit (seconds, minutes, hours).")
                
        self.consume(TokenType.DO, "Expected 'do' after time interval.")
        self.consume(TokenType.LPAREN, "Expected '(' before command.")
        
        cmd_tokens = []
        while not self.check(TokenType.RPAREN) and not self.is_at_end():
            token = self.advance()
            # If it's a string, we need to wrap it in quotes
            if token.type == TokenType.STRING:
                cmd_tokens.append(f'"{token.lexeme}"')
            else:
                cmd_tokens.append(token.lexeme)
                
        self.consume(TokenType.RPAREN, "Expected ')' after command.")
        command_str = " ".join(cmd_tokens)
        
        stmt = CronStmt(line=self.previous().line, column=self.previous().column)
        stmt.interval_seconds = interval
        stmt.command_str = command_str
        return stmt
