from enum import Enum, auto
from dataclasses import dataclass

class TokenType(Enum):
    IDENTIFIER = auto()
    STRING = auto()
    NUMBER = auto()
    JSON_LITERAL = auto()

    # Keywords
    SCOOP = auto()
    FROM = auto()
    WHERE = auto()
    MENTIONING = auto()
    INCLUDE = auto()
    MEANING = auto()
    COUNT = auto()
    POUR = auto()
    INTO = auto()
    DRAIN = auto()
    AND = auto()
    OR = auto()
    LIMIT = auto()
    ORDER = auto()
    BY = auto()
    NEWEST = auto()
    OLDEST = auto()
    RELEVANCE = auto()
    SHAPE = auto()
    BUCKET = auto()
    BOND = auto()
    TO = auto()

    # Operators
    EQ = auto()      # =
    NEQ = auto()     # !=
    GT = auto()      # >
    GTE = auto()     # >=
    LT = auto()      # <
    LTE = auto()     # <=
    COMMA = auto()   # ,
    LPAREN = auto()  # (
    RPAREN = auto()  # )

    EOF = auto()
    UNKNOWN = auto()

KEYWORDS = {
    "scoop": TokenType.SCOOP,
    "from": TokenType.FROM,
    "where": TokenType.WHERE,
    "mentioning": TokenType.MENTIONING,
    "include": TokenType.INCLUDE,
    "meaning": TokenType.MEANING,
    "count": TokenType.COUNT,
    "pour": TokenType.POUR,
    "into": TokenType.INTO,
    "drain": TokenType.DRAIN,
    "and": TokenType.AND,
    "or": TokenType.OR,
    "limit": TokenType.LIMIT,
    "order": TokenType.ORDER,
    "by": TokenType.BY,
    "newest": TokenType.NEWEST,
    "oldest": TokenType.OLDEST,
    "relevance": TokenType.RELEVANCE,
    "shape": TokenType.SHAPE,
    "bucket": TokenType.BUCKET,
    "bond": TokenType.BOND,
    "to": TokenType.TO,
}

@dataclass
class Token:
    type: TokenType
    lexeme: str
    line: int
    column: int
