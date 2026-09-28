from .planner import PlanEnumerator
from .cost_model import CostModel

class Explainer:
    def __init__(self):
        self.enumerator = PlanEnumerator()
        self.cost_model = CostModel()

    def explain(self, ast_node):
        plans = self.enumerator.enumerate_plans(ast_node)
        
        print(f"--- QUERY PLAN EXPLAIN ---")
        
        best_plan = self.cost_model.select_best_plan(plans)
        print(f"Chosen Plan: {best_plan.name} (Estimated Cost: {best_plan.estimate_cost(self.cost_model):.2f} ms)")
        
        print("\nRejected Plans:")
        for p in plans:
            if p != best_plan:
                print(f"  - {p.name} (Estimated Cost: {p.estimate_cost(self.cost_model):.2f} ms)")
        
        return best_plan
