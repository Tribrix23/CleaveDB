from enum import Enum, auto
from dataclasses import dataclass
from typing import Any, Optional

class TokenType(Enum):
    # Verbs
    SCOOP = auto()    # query/read
    POUR = auto()     # insert/upsert
    DRAIN = auto()    # delete
    FLOW = auto()     # move/copy between buckets
    BOND = auto()     # declare relationship
    DISTILL = auto()  # aggregate
    FOLLOW = auto()   # traverse bonds
    SHAPE = auto()    # create/configure bucket
    PEER = auto()     # explain/inspect
    CHANGE = auto()   # partial update
    COUNT = auto()    # count matching documents
    INDEX = auto()    # declare index
    HEAL = auto()     # repair indexes
    SHOW = auto()     # list metadata
    DESCRIBE = auto() # describe a bucket
    SUGGEST = auto()  # ask attention for suggestions

    # Clauses
    FROM = auto()
    INTO = auto()
    WHERE = auto()
    WHOSE = auto()      # bond traversal predicate
    MEANING = auto()    # semantic search
    MENTIONING = auto() # keyword search (BM25)
    NEAR = auto()       # graph proximity
    WITHIN = auto()     # depth for NEAR
    SINCE = auto()      # time lower bound
    UNTIL = auto()      # time upper bound
    ORDER = auto()
    BY = auto()
    LIMIT = auto()
    INCLUDE = auto()    # join related documents
    MANY = auto()       # POUR MANY
    SET = auto()        # CHANGE
    TO = auto()
    BEFORE = auto()     # DRAIN...BEFORE
    ON = auto()         # INDEX, BOND
    DELETE = auto()     # BOND ON DELETE
    THROUGH = auto()    # FOLLOW
    DIRECTION = auto()  # FOLLOW
    DEPTH = auto()      # FOLLOW
    STRENGTH = auto()   # BOND
    CARDINALITY = auto()# BOND
    WHEN = auto()       # FLOW
    ACTION = auto()     # FLOW
    COMPRESSION = auto()# SHAPE
    TTL = auto()        # SHAPE
    MAX = auto()        # SHAPE
    DOCUMENTS = auto()  # SHAPE
    VERSIONED = auto()  # SHAPE
    PROJECTION = auto() # SHAPE PROJECTION
    BUCKET = auto()     # SHAPE BUCKET
    ATTENTION = auto()  # PEER INTO ATTENTION
    BONDS = auto()      # SHOW BONDS
    BUCKETS = auto()    # SHOW BUCKETS
    INDEXES = auto()    # SHOW INDEXES
    STATS = auto()      # SHOW STATS
    ALL = auto()        # HEAL ALL
    AND = auto()
    OR = auto()
    NOT = auto()
    POLICY = auto()
    FOR = auto()
    USING = auto()
    READ = auto()
    WRITE = auto()
    CONTEXT = auto()


    # Sort keywords
    NEWEST = auto()
    OLDEST = auto()
    RELEVANCE = auto()

    # Bond strength
    SOFT = auto()
    FIRM = auto()
    STRICT = auto()

    # On-delete
    KEEP = auto()
    RESTRICT = auto()
    CASCADE = auto()

    # Cardinality
    ONE = auto()
    # MANY already defined

    # Flow actions
    COPY = auto()
    MOVE = auto()

    # Direction
    OUT = auto()
    IN = auto()
    BOTH = auto()

    # Aggregation
    TOTAL = auto()
    AVERAGE = auto()
    MIN = auto()
    MAX_AGG = auto()
    SPREAD = auto()
    OF = auto()

    # Operators
    EQ = auto()      # =
    NEQ = auto()     # !=
    GT = auto()      # >
    GTE = auto()     # >=
    LT = auto()      # <
    LTE = auto()     # <=

    # Punctuation
    DOT = auto()      # .
    SLASH = auto()    # /
    COMMA = auto()    # ,
    LBRACE = auto()   # {
    RBRACE = auto()   # }
    LBRACKET = auto() # [
    RBRACKET = auto() # ]
    COLON = auto()    # :
    LPAREN = auto()   # (
    RPAREN = auto()   # )
    STAR = auto()     # *

    # Literals
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    IDENTIFIER = auto()

    # Special
    NEWLINE = auto()
    EOF = auto()
    UNKNOWN = auto()

KEYWORDS = {
    'policy': TokenType.POLICY,
    'for': TokenType.FOR,
    'using': TokenType.USING,
    'read': TokenType.READ,
    'write': TokenType.WRITE,
    'context': TokenType.CONTEXT,

    'scoop': TokenType.SCOOP,
    'pour': TokenType.POUR,
    'drain': TokenType.DRAIN,
    'flow': TokenType.FLOW,
    'bond': TokenType.BOND,
    'distill': TokenType.DISTILL,
    'follow': TokenType.FOLLOW,
    'shape': TokenType.SHAPE,
    'peer': TokenType.PEER,
    'change': TokenType.CHANGE,
    'count': TokenType.COUNT,
    'index': TokenType.INDEX,
    'heal': TokenType.HEAL,
    'show': TokenType.SHOW,
    'describe': TokenType.DESCRIBE,
    'suggest': TokenType.SUGGEST,
    'from': TokenType.FROM,
    'into': TokenType.INTO,
    'where': TokenType.WHERE,
    'whose': TokenType.WHOSE,
    'meaning': TokenType.MEANING,
    'mentioning': TokenType.MENTIONING,
    'near': TokenType.NEAR,
    'within': TokenType.WITHIN,
    'since': TokenType.SINCE,
    'until': TokenType.UNTIL,
    'order': TokenType.ORDER,
    'by': TokenType.BY,
    'limit': TokenType.LIMIT,
    'include': TokenType.INCLUDE,
    'many': TokenType.MANY,
    'set': TokenType.SET,
    'to': TokenType.TO,
    'before': TokenType.BEFORE,
    'on': TokenType.ON,
    'delete': TokenType.DELETE,
    'through': TokenType.THROUGH,
    'direction': TokenType.DIRECTION,
    'depth': TokenType.DEPTH,
    'strength': TokenType.STRENGTH,
    'cardinality': TokenType.CARDINALITY,
    'when': TokenType.WHEN,
    'action': TokenType.ACTION,
    'compression': TokenType.COMPRESSION,
    'ttl': TokenType.TTL,
    'max': TokenType.MAX,
    'documents': TokenType.DOCUMENTS,
    'versioned': TokenType.VERSIONED,
    'projection': TokenType.PROJECTION,
    'bucket': TokenType.BUCKET,
    'attention': TokenType.ATTENTION,
    'bonds': TokenType.BONDS,
    'buckets': TokenType.BUCKETS,
    'indexes': TokenType.INDEXES,
    'stats': TokenType.STATS,
    'all': TokenType.ALL,
    'and': TokenType.AND,
    'or': TokenType.OR,
    'not': TokenType.NOT,
    'newest': TokenType.NEWEST,
    'oldest': TokenType.OLDEST,
    'relevance': TokenType.RELEVANCE,
    'soft': TokenType.SOFT,
    'firm': TokenType.FIRM,
    'strict': TokenType.STRICT,
    'keep': TokenType.KEEP,
    'restrict': TokenType.RESTRICT,
    'cascade': TokenType.CASCADE,
    'one': TokenType.ONE,
    'copy': TokenType.COPY,
    'move': TokenType.MOVE,
    'out': TokenType.OUT,
    'in': TokenType.IN,
    'both': TokenType.BOTH,
    'total': TokenType.TOTAL,
    'average': TokenType.AVERAGE,
    'min': TokenType.MIN,
    'max_agg': TokenType.MAX_AGG,
    'spread': TokenType.SPREAD,
    'of': TokenType.OF,
}

@dataclass
class Token:
    type: TokenType
    lexeme: str
    line: int
    column: int
    value: Optional[Any] = None

    # Security Features
    POLICY = auto()
    FOR = auto()
    USING = auto()
    READ = auto()
    WRITE = auto()
    CONTEXT = auto()
