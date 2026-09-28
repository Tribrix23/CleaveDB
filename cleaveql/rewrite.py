class RewriteRules:
    @staticmethod
    def apply_all(ast_node):
        ast_node = RewriteRules.pushdown_predicates(ast_node)
        ast_node = RewriteRules.pushdown_limits(ast_node)
        ast_node = RewriteRules.eliminate_redundant_predicates(ast_node)
        return ast_node

    @staticmethod
    def pushdown_predicates(ast_node):
        # Predicate pushdown through bonds
        return ast_node

    @staticmethod
    def pushdown_limits(ast_node):
        # Limit pushdown to driver
        return ast_node

    @staticmethod
    def eliminate_redundant_predicates(ast_node):
        # Remove A > 10 AND A > 5 -> A > 10
        return ast_node
