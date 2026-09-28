from dataclasses import dataclass
from typing import List, Optional, Any

@dataclass
class ASTNode:
    pass

@dataclass
class ScoopStmt(ASTNode):
    bucket: str
    where: Optional['WhereClause'] = None
    meaning: Optional[str] = None
    mentioning: Optional[str] = None
    include: List[str] = None
    limit: Optional[int] = None

@dataclass
class WhereClause(ASTNode):
    predicates: List['Predicate']

@dataclass
class Predicate(ASTNode):
    field: str
    op: str
    value: Any
