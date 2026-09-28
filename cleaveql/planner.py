from .cost_model import CostModel

class PlanNode:
    def __init__(self, name):
        self.name = name
        self.children = []

    def estimate_cost(self, cost_model: CostModel):
        return 1.0

class PlanEnumerator:
    def __init__(self):
        pass

    def enumerate_plans(self, ast_node):
        """
        Generates 2-5 candidate plans per query:
        - text-driver
        - numeric-driver
        - bond-traversal
        - time-scan
        - full-scan
        """
        plans = []
        
        # 1. Full Scan Plan (Baseline)
        full_scan = PlanNode("FullScan")
        plans.append(full_scan)
        
        # 2. Text Driver (if mentioning is present)
        if getattr(ast_node, "mentioning", None):
            text_driver = PlanNode("TextSearchScan")
            plans.append(text_driver)
            
        # 3. Numeric Driver (if where clause has numbers)
        if getattr(ast_node, "where", None):
            numeric_driver = PlanNode("NumericProbe")
            plans.append(numeric_driver)
            
        return plans
