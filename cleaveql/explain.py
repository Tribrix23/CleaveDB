from .planner import PlanEnumerator, PlanNode
from .cost_model import CostModel
from .rewrite import RewriteRules

class Explainer:
    def __init__(self, total_pages=1000, total_rows=100000):
        self.enumerator = PlanEnumerator(total_pages=total_pages, total_rows=total_rows)
        self.cost_model = CostModel()

    def explain(self, ast_node):
        ast_node = RewriteRules.apply_all(ast_node)
        plans = self.enumerator.enumerate_plans(ast_node)
        best_plan = self.cost_model.select_best_plan(plans)
        best_cost = best_plan.estimate_cost(self.cost_model)
        lines = []
        lines.append("--- QUERY PLAN ---")
        lines.append(f"Chosen Plan: {best_plan.name}")
        lines.append(f"  Estimated Cost: {best_cost:.2f} ms")
        lines.append(f"  Selectivity: {best_plan.selectivity:.2%}")
        lines.append(f"  Estimated Rows: {int(best_plan.estimated_rows * best_plan.selectivity)}")
        rewrites = []
        if getattr(ast_node, '_predicate_pushed', False):
            rewrites.append('predicate-pushdown')
        if getattr(ast_node, '_limit_pushed', False):
            rewrites.append('limit-pushdown')
        if rewrites:
            lines.append(f"  Rewrites: {', '.join(rewrites)}")
        lines.append("")
        lines.append("Rejected Plans:")
        for p in plans:
            if p.name != best_plan.name:
                cost = p.estimate_cost(self.cost_model)
                lines.append(f"  - {p.name} (Cost: {cost:.2f} ms, Selectivity: {p.selectivity:.2%})")
        output = "\n".join(lines)
        return {'chosen': best_plan.name, 'cost': best_cost, 'output': output}
