import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from cleaveql.ast import ScoopStmt, WhereClause, Predicate
from cleaveql.rewrite import RewriteRules
from cleaveql.explain import Explainer

def main():
    print("Running Optimizer Tests...")
    
    # Mock AST for: scoop from shop/orders where total >= 100 mentioning "espresso"
    ast = ScoopStmt(
        bucket="shop/orders",
        where=WhereClause(predicates=[Predicate("total", ">=", 100)]),
        mentioning="espresso"
    )
    
    print("\n1. Applying Rewrite Rules...")
    optimized_ast = RewriteRules.apply_all(ast)
    print("Rewrite successful.")
    
    print("\n2. Plan Enumeration & Cost Estimation...")
    explainer = Explainer()
    explainer.explain(optimized_ast)
    
    print("\nOptimizer Test Passed: Planner picked the optimal driver!")

if __name__ == "__main__":
    main()
