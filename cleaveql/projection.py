class ProjectionBucket:
    def __init__(self, name: str, source_bucket: str, filters: dict):
        self.name = name
        self.source_bucket = source_bucket
        self.filters = filters

    def rewrite_query(self, ast_node):
        """
        Rewrites a query against the projection bucket into a query
        against the source bucket with the projection filters applied.
        """
        if getattr(ast_node, "bucket", None) == self.name:
            ast_node.bucket = self.source_bucket
            # Merge filters into the WHERE clause
            # (Mock implementation)
        return ast_node
