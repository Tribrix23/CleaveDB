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
    LISTEN = auto()   # websocket subscription
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
    AS = auto()
    AS_OF = auto()
    RELATED = auto()
    LABEL = auto()
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
    DOWN = auto()
    UP = auto()
    GOING = auto()
    ARRANGED = auto()
    ANY = auto()
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
    MATCHING = auto()
    IS = auto()
    RANDOM = auto()
    LAST = auto()
    FIRST = auto()
    THE = auto()
    TALLY = auto()
    LOWEST = auto()
    EXPIRING = auto()
    MUTUAL = auto()
    EXCLUSIVELY = auto()
    CONFIDENCE = auto()
    AFFINITY = auto()
    WITH = auto()
    HIGHEST = auto()
    GROUPED = auto()
    UNIQUE = auto()
    ONLY = auto()
    EVERYTHING = auto()
    YIELD = auto()
    SALVAGE = auto()
    INCINERATE = auto()
    POLICY = auto()
    FIND = auto()       # Alias for SCOOP
    UPDATE = auto()     # Alias for CHANGE
    LINK = auto()

    EXPIRES = auto()
    DAYS = auto()
       # Alias for BOND
    IF = auto()         # Alias for ONLY WHEN
    
    MATCH = auto()
    EDGE_START = auto()   # -[
    EDGE_RIGHT = auto()   # ]->
    EDGE_LEFT = auto()    # <-[
    EDGE_END = auto()     # ]-
    CANDIDATE = auto()  # Flag to show dormant bonds
    TRACE = auto()      # Alias for SCOOP CHAIN
    REWIND = auto()
    ENFORCE = auto()
    OVERWRITE = auto()
    CURRENT = auto()
    REPLACE = auto()
    UPDATES = auto()
    LEAST = auto()
    RECENTLY = auto()
    USED = auto()
    SECURITY = auto()
    ALLOW = auto()
    BONDED = auto()
    AUTHENTICATE = auto()
    DESC = auto()       # Alias for DOWN
    ASC = auto()        # Alias for UP
    SORTED = auto()     # Alias for ARRANGED
    MASK = auto()
    FOR = auto()
    USING = auto()
    READ = auto()
    WRITE = auto()
    CONTEXT = auto()
    SECRET = auto()
    MY = auto()
    ROLE = auto()
    UNLINK = auto()
    SEVER = auto()
    DROP = auto()


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
    EVERY = auto()
    DAY = auto()
    MIDNIGHT = auto()
    DO = auto()
    MINUTE = auto()
    MINUTES = auto()
    HOUR = auto()
    HOURS = auto()
    SECOND = auto()
    SECONDS = auto()
    UNKNOWN = auto()

KEYWORDS = {
    "expires": TokenType.EXPIRES,
    "days": TokenType.DAYS,
    "match": TokenType.MATCH,
    "listen": TokenType.LISTEN,
    'seconds': TokenType.SECONDS,
    'second': TokenType.SECOND,
    'hours': TokenType.HOURS,
    'hour': TokenType.HOUR,
    'minutes': TokenType.MINUTES,
    'minute': TokenType.MINUTE,
    'do': TokenType.DO,
    'midnight': TokenType.MIDNIGHT,
    'day': TokenType.DAY,
    'every': TokenType.EVERY,
    'policy': TokenType.POLICY,
    'mask': TokenType.MASK,
    'for': TokenType.FOR,
    'using': TokenType.USING,
    'read': TokenType.READ,
    'write': TokenType.WRITE,
    'context': TokenType.CONTEXT,
    'secret': TokenType.SECRET,
    'my': TokenType.MY,
    'role': TokenType.ROLE,
    'unlink': TokenType.UNLINK,
    'sever': TokenType.SEVER,
    'drop': TokenType.DROP,

    'scoop': TokenType.SCOOP,
    'find': TokenType.FIND,
    'trace': TokenType.TRACE,
    'desc': TokenType.DESC,
    'asc': TokenType.ASC,
    'sorted': TokenType.SORTED,
    'pour': TokenType.POUR,
    'drain': TokenType.DRAIN,
    'flow': TokenType.FLOW,
    'bond': TokenType.BOND,
    'link': TokenType.LINK,
    'if': TokenType.IF,
    'candidate': TokenType.CANDIDATE,
    'distill': TokenType.DISTILL,
    'rewind': TokenType.REWIND,
    'enforce': TokenType.ENFORCE,
    'overwrite': TokenType.OVERWRITE,
    'current': TokenType.CURRENT,
    'replace': TokenType.REPLACE,
    'updates': TokenType.UPDATES,
    'least': TokenType.LEAST,
    'recently': TokenType.RECENTLY,
    'used': TokenType.USED,
    'security': TokenType.SECURITY,
    'allow': TokenType.ALLOW,
    'bonded': TokenType.BONDED,
    'authenticate': TokenType.AUTHENTICATE,
    'follow': TokenType.FOLLOW,
    'shape': TokenType.SHAPE,
    'peer': TokenType.PEER,
    'change': TokenType.CHANGE,
    'update': TokenType.UPDATE,
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
    'down': TokenType.DOWN,
    'up': TokenType.UP,
    'going': TokenType.GOING,
    'arranged': TokenType.ARRANGED,
    'any': TokenType.ANY,
    'set': TokenType.SET,
    'to': TokenType.TO,
    'as': TokenType.AS,
    'related': TokenType.RELATED,
    'label': TokenType.LABEL,
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
    'matching': TokenType.MATCHING,
    'is': TokenType.IS,
    'random': TokenType.RANDOM,
    'last': TokenType.LAST,
    'first': TokenType.FIRST,
    'the': TokenType.THE,
    'tally': TokenType.TALLY,
    'lowest': TokenType.LOWEST,
    'expiring': TokenType.EXPIRING,
    'mutual': TokenType.MUTUAL,
    'exclusively': TokenType.EXCLUSIVELY,
    'confidence': TokenType.CONFIDENCE,
    'affinity': TokenType.AFFINITY,
    'with': TokenType.WITH,
    'highest': TokenType.HIGHEST,
    'grouped': TokenType.GROUPED,
    'unique': TokenType.UNIQUE,
    'only': TokenType.ONLY,
    'everything': TokenType.EVERYTHING,
    'yield': TokenType.YIELD,
    'salvage': TokenType.SALVAGE,
    'incinerate': TokenType.INCINERATE,
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
