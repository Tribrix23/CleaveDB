from .ast import *

class RewriteRules:
    @staticmethod
    def apply_all(ast_node):
        ast_node = RewriteRules.pushdown_predicates(ast_node)
        ast_node = RewriteRules.pushdown_limits(ast_node)
        ast_node = RewriteRules.eliminate_redundant_predicates(ast_node)
        ast_node = RewriteRules.collapse_bond_chains(ast_node)
        return ast_node

    @staticmethod
    def pushdown_predicates(ast_node):
        if not isinstance(ast_node, ScoopStmt):
            return ast_node
        if ast_node.where and ast_node.include:
            ast_node._predicate_pushed = True
        return ast_node

    @staticmethod
    def pushdown_limits(ast_node):
        if not isinstance(ast_node, ScoopStmt):
            return ast_node
        if ast_node.limit and not ast_node.order_by:
            ast_node._limit_pushed = True
        return ast_node

    @staticmethod
    def eliminate_redundant_predicates(ast_node):
        if not isinstance(ast_node, (ScoopStmt, CountStmt)):
            return ast_node
        where = getattr(ast_node, 'where', None)
        if not where or not hasattr(where, 'predicates'):
            return ast_node
        seen = set()
        unique_preds = []
        unique_conns = []
        for i, pred in enumerate(where.predicates):
            key = (getattr(pred, 'field', ''), getattr(pred, 'op', ''), str(getattr(pred, 'value', '')))
            if key not in seen:
                seen.add(key)
                unique_preds.append(pred)
                if i > 0 and i - 1 < len(where.connectives or []):
                    unique_conns.append(where.connectives[i-1])
        where.predicates = unique_preds
        if where.connectives:
            where.connectives = unique_conns
        return ast_node

    @staticmethod
    def collapse_bond_chains(ast_node):
        return ast_node
