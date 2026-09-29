from dataclasses import dataclass, field
from typing import List, Optional, Any, Union

@dataclass
class ASTNode:
    line: int = 0
    column: int = 0

@dataclass
class Predicate(ASTNode):
    field: str = ""
    op: str = ""
    value: Any = None

@dataclass
class WhereClause(ASTNode):
    predicates: List[Predicate] = field(default_factory=list)
    connectives: List[str] = field(default_factory=list)

@dataclass
class FieldAssign(ASTNode):
    field: str = ""
    value: Any = None

# Query statements
@dataclass
class ScoopStmt(ASTNode):
    bucket: str = ""
    where: Optional[WhereClause] = None
    mentioning: Optional[str] = None
    meaning: Optional[str] = None
    include: List[str] = field(default_factory=list)
    limit: Optional[int] = None
    order_by: Optional[str] = None
    order_dir: Optional[str] = None

@dataclass 
class CountStmt(ASTNode):
    bucket: str = ""
    where: Optional[WhereClause] = None

@dataclass
class DistillStmt(ASTNode):
    bucket: str = ""
    agg_func: str = ""  # total, average, min, max, spread
    agg_field: str = ""
    where: Optional[WhereClause] = None

@dataclass
class FollowStmt(ASTNode):
    doc_key: str = ""
    bond_name: Optional[str] = None
    direction: Optional[str] = None # out, in, both
    depth: Optional[int] = None
    limit: Optional[int] = None

# Mutation statements  
@dataclass
class PourStmt(ASTNode):
    bucket: str = ""
    doc_id: Optional[str] = None
    json_body: Any = None

@dataclass
class PourManyStmt(ASTNode):
    bucket: str = ""
    json_array: List[Any] = field(default_factory=list)

@dataclass
class ChangeStmt(ASTNode):
    bucket: str = ""
    doc_id: str = ""
    assignments: List[FieldAssign] = field(default_factory=list)

@dataclass
class DrainStmt(ASTNode):
    bucket: str = ""
    doc_id: Optional[str] = None
    where: Optional[WhereClause] = None
    before: Optional[str] = None

# Declaration statements
@dataclass
class ShapeBucketStmt(ASTNode):
    path: str = ""
    compression: Optional[str] = None
    ttl: Optional[str] = None
    max_documents: Optional[int] = None
    versioned: bool = False

@dataclass
class ShapeProjectionStmt(ASTNode):
    path: str = ""
    from_bucket: str = ""
    where: Optional[WhereClause] = None

@dataclass
class BondStmt(ASTNode):
    name: str = ""
    from_field: str = ""
    to_bucket: str = ""
    strength: str = "" # soft, firm, strict
    on_delete: str = "" # keep, restrict, cascade
    cardinality: str = "" # one, many

@dataclass
class IndexStmt(ASTNode):
    bucket: str = ""
    fields: List[str] = field(default_factory=list)

@dataclass 
class FlowStmt(ASTNode):
    name: str = ""
    from_bucket: str = ""
    to_bucket: str = ""
    when: Optional[WhereClause] = None
    action: str = "" # copy, move

@dataclass
class HealStmt(ASTNode):
    target: str = "" # bonds, indexes, all

# Meta statements
@dataclass
class ShowStmt(ASTNode):
    target: str = "" # buckets, bonds, indexes, stats

@dataclass
class DescribeStmt(ASTNode):
    bucket: str = ""

@dataclass
class PeerStmt(ASTNode):
    target_stmt: Optional[ASTNode] = None
    attention: bool = False

@dataclass
class SuggestStmt(ASTNode):
    target: str = "" # bonds
