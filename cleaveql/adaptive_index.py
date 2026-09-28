class AdaptiveIndexer:
    def __init__(self):
        self.query_frequency = {}

    def observe_query(self, ast_node):
        # Track un-indexed field query frequency
        if getattr(ast_node, "where", None):
            for pred in ast_node.where.predicates:
                field = pred.field
                self.query_frequency[field] = self.query_frequency.get(field, 0) + 1

    def suggest_indexes(self):
        # Auto-suggest via REPL hint
        suggestions = []
        for field, freq in self.query_frequency.items():
            if freq > 10:
                suggestions.append(f"Consider: index {field}")
        return suggestions
