from .ast import ScoopStmt, WhereClause, Predicate

class ProjectionBucket:
    def __init__(self, name, source_bucket, filter_predicates=None):
        self.name = name
        self.source_bucket = source_bucket
        self.filter_predicates = filter_predicates or []

    def rewrite_query(self, ast_node):
        if not isinstance(ast_node, ScoopStmt):
            return ast_node
        if getattr(ast_node, 'bucket', None) != self.name:
            return ast_node
        ast_node.bucket = self.source_bucket
        if self.filter_predicates:
            proj_preds = [Predicate(field=f, op=op, value=v) for f, op, v in self.filter_predicates]
            existing_where = ast_node.where
            if existing_where and hasattr(existing_where, 'predicates'):
                combined = proj_preds + existing_where.predicates
                conns = ['and'] * (len(combined) - 1)
                ast_node.where = WhereClause(predicates=combined, connectives=conns)
            else:
                conns = ['and'] * max(0, len(proj_preds) - 1)
                ast_node.where = WhereClause(predicates=proj_preds, connectives=conns)
        return ast_node

class ProjectionRegistry:
    def __init__(self):
        self.projections = {}

    def register(self, projection):
        self.projections[projection.name] = projection

    def rewrite_if_projection(self, ast_node):
        bucket = getattr(ast_node, 'bucket', None)
        if bucket and bucket in self.projections:
            return self.projections[bucket].rewrite_query(ast_node)
        return ast_node
