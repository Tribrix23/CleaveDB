from .cost_model import CostModel
from .ast import *

class PlanNode:
    def __init__(self, name, estimated_pages=0, estimated_rows=0, index_depth=0, selectivity=1.0):
        self.name = name
        self.estimated_pages = estimated_pages
        self.estimated_rows = estimated_rows
        self.index_depth = index_depth
        self.selectivity = selectivity
        self.children = []

    def estimate_cost(self, cost_model):
        if self.name == 'FullScan':
            return cost_model.estimate_scan_cost(self.estimated_pages, self.estimated_rows)
        elif self.name in ('TextSearchScan', 'NumericProbe'):
            return cost_model.estimate_index_cost(self.index_depth, int(self.estimated_rows * self.selectivity))
        elif self.name == 'BondTraversal':
            return cost_model.estimate_index_cost(self.index_depth, self.estimated_rows) * 1.5
        elif self.name == 'TimeScan':
            return cost_model.estimate_scan_cost(self.estimated_pages, self.estimated_rows) * 0.3
        return cost_model.estimate_scan_cost(self.estimated_pages, self.estimated_rows)

class PlanEnumerator:
    def __init__(self, total_pages=1000, total_rows=100000, index_depth=3):
        self.total_pages = total_pages
        self.total_rows = total_rows
        self.index_depth = index_depth

    def enumerate_plans(self, ast_node):
        plans = []
        plans.append(PlanNode('FullScan', self.total_pages, self.total_rows))
        if getattr(ast_node, 'mentioning', None):
            plans.append(PlanNode('TextSearchScan', self.total_pages, self.total_rows, self.index_depth, selectivity=0.01))
        if getattr(ast_node, 'where', None):
            plans.append(PlanNode('NumericProbe', self.total_pages, self.total_rows, self.index_depth, selectivity=0.1))
        if hasattr(ast_node, 'bond') and getattr(ast_node, 'bond', None):
            plans.append(PlanNode('BondTraversal', self.total_pages, self.total_rows, self.index_depth, selectivity=0.05))
        if getattr(ast_node, 'order_by', None) in ('newest', 'oldest'):
            plans.append(PlanNode('TimeScan', self.total_pages, self.total_rows))
        return plans
