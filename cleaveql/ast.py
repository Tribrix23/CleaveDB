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
    matching: Optional[dict] = None
    yield_fields: List[str] = field(default_factory=list)
    mode: str = "EVERYTHING"
    mode_count: Optional[int] = None
    whose_field: Optional[str] = None
    whose_value: Any = None
    limit: Optional[int] = None
    order_by: Optional[str] = None
    order_dir: Optional[str] = None
    related_label: Optional[str] = None
    related_source: Optional[str] = None
    target_field: Optional[str] = None
    group_by: Optional[str] = None
    order_field: Optional[str] = None
    as_of: Optional[Any] = None

@dataclass 
class CountStmt(ASTNode):
    bucket: str = ""
    where: Optional[WhereClause] = None

@dataclass
class DistillStmt(ASTNode):
    bucket: str = ""
    agg_function: str = ""  # total/sum, average, min, max, spread
    field: str = ""
    group_by: Optional[str] = None
    alias: Optional[str] = None
    where: Optional[WhereClause] = None

@dataclass
class FollowStmt(ASTNode):
    doc_key: str = ""
    bond_name: Optional[str] = None
    direction: Optional[str] = None # out, in, both
    depth: Optional[int] = None
    as_of: Optional[str] = None
    limit: Optional[int] = None

# Mutation statements  
@dataclass
class PourStmt(ASTNode):
    bucket: str = ""
    doc_id: Optional[str] = None
    json_body: Any = None
    secret: Optional[str] = None
    ttl: Optional[int] = None

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

@dataclass
class SalvageStmt(ASTNode):
    doc_id: Optional[str] = None
    everything: bool = False
    
@dataclass
class IncinerateStmt(ASTNode):
    doc_id: Optional[str] = None
    everything: bool = False

# Declaration statements
class ShapeViewStmt(ASTNode):
    def __init__(self, view_name, source_bucket, group_field, sum_field):
        self.view_name = view_name
        self.source_bucket = source_bucket
        self.group_field = group_field
        self.sum_field = sum_field

@dataclass
class HelpStmt(ASTNode):
    pass

@dataclass
class ShapeWebhookStmt(ASTNode):
    name: str = ""
    bucket: str = ""
    action_filter: str = ""
    url: str = ""

@dataclass
class ShapeBucketStmt(ASTNode):
    path: str = ""
    compression: Optional[str] = None
    ttl: Optional[str] = None
    max_documents: Optional[int] = None
    versioned: bool = False
    audited: bool = False

@dataclass
class ShapeProjectionStmt(ASTNode):
    path: str = ""
    from_bucket: str = ""
    where: Optional[WhereClause] = None

@dataclass
class BondStmt(ASTNode):
    source_gid: str = ""
    target_gid: str = ""
    mutual: bool = False
    label: str = ""

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
    cost: bool = False

@dataclass
@dataclass
class FindHowStmt(ASTNode):
    bond_name: str = ""
    doc_id: str = ""
    start_time: str = ""
    end_time: str = ""

@dataclass
class SuggestStmt(ASTNode):
    target: str = "" # bonds

@dataclass
class PolicyStmt(ASTNode):
    bucket: str = ""
    name: str = ""
    action: str = ""
    condition: Any = None
    algorithm: str = "" 

@dataclass
class SetContextStmt(ASTNode):
    key: str = ""
    value: Any = None

@dataclass
class MaskStmt(ASTNode):
    field: str = ''
    bucket: str = ''
    condition: Any = None


@dataclass
class CronStmt(ASTNode):
    interval_seconds: int = 0
    command_str: str = ''

class RewindStmt:
    def __init__(self, doc_id, target_time, line=0, column=0):
        self.type = "RewindStmt"
        self.doc_id = doc_id
        self.target_time = target_time
        self.line = line
        self.column = column

class AuthenticateStmt:
    def __init__(self, user_id, line=0, column=0):
        self.type = "AuthenticateStmt"
        self.user_id = user_id
        self.line = line
        self.column = column

@dataclass

class GraphNode:
    def __init__(self, alias: str, bucket: str):
        self.alias = alias
        self.bucket = bucket

class GraphEdge:
    def __init__(self, label: str, direction: str):
        self.label = label
        self.direction = direction

class MatchStmt(ASTNode):
    def __init__(self, nodes: list, edges: list, where=None):
        self.nodes = nodes
        self.edges = edges
        self.where = where

@dataclass
class SeverStmt(ASTNode):
    source_gid: str = ""
    target_gid: str = ""
    label: str = ""

@dataclass
class DropSecurityStmt(ASTNode):
    name: str = ""
    bucket: str = ""

@dataclass
class ListenStmt(ASTNode):
    target_bucket: str = ""
    target_gid: Optional[str] = None

@dataclass
class MigrateStmt(ASTNode):
    bucket: str = ''
    src_json: Any = None
    dst_json: Any = None

class BeginStmt(ASTNode):
    pass

class CommitStmt(ASTNode):
    pass

class RollbackStmt(ASTNode):
    pass

class TriggerStmt(ASTNode):
    def __init__(self, event, bucket, query_template):
        self.event = event
        self.bucket = bucket
        self.query_template = query_template

@dataclass
class RateLimitStmt(ASTNode):
    role: str = ''
    limit: int = 0

@dataclass
class DropBucketStmt(ASTNode):
    bucket: str = ""

@dataclass
class RestoreBucketStmt(ASTNode):
    bucket: str = ""

@dataclass
class GuardStmt(ASTNode):
    bucket: str = ""
    rules: List[dict] = field(default_factory=list)


@dataclass
class EnrichStmt(ASTNode):
    bucket: str = ""
    rules: List[dict] = field(default_factory=list)


class ShapeReplicaStmt(ASTNode):
    def __init__(self, target_bucket: str, source_bucket: str, when=None, show_fields=None):
        self.target_bucket = target_bucket
        self.source_bucket = source_bucket
        self.when = when
        self.show_fields = show_fields or []


@dataclass
class ForecastStmt(ASTNode):
    bucket: str = ""
    value_field: str = ""
    time_field: str = ""
    horizon: int = 0
    time_unit: str = ""
    method: str = ""
    window: int = 0


@dataclass
class FilterStage(ASTNode):
    where: Any = None

@dataclass
class GroupStage(ASTNode):
    group_field: str = ""
    aggregations: List[dict] = field(default_factory=list)

@dataclass
class SortStage(ASTNode):
    sort_field: str = ""
    direction: str = "UP"

@dataclass
class LimitStage(ASTNode):
    limit: int = 0

@dataclass
class ProjectStage(ASTNode):
    fields: List[str] = field(default_factory=list)

@dataclass
class PipeStmt(ASTNode):
    source_bucket: str = ""
    stages: List[ASTNode] = field(default_factory=list)
