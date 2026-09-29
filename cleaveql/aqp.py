"""Adaptive Query Planner (AQP) — Learned cost estimation with online weight updates.

Uses exponential moving average to learn from actual query execution times
and adjust cost predictions without a backprop library.
"""
import math
import json
import os
from typing import Dict, Optional, Tuple


class AdaptiveQueryPlanner:
    """Learned cost estimator that improves with query feedback.
    
    Maintains per-plan-type weights that are updated online
    after each query execution using exponential moving average.
    """

    DEFAULT_WEIGHTS = {
        "FullScan": {"page_weight": 0.1, "row_weight": 0.001, "bias": 5.0},
        "TextSearchScan": {"page_weight": 0.01, "row_weight": 0.005, "bias": 2.0},
        "NumericProbe": {"page_weight": 0.02, "row_weight": 0.003, "bias": 1.5},
        "BondTraversal": {"page_weight": 0.05, "row_weight": 0.008, "bias": 3.0},
        "TimeScan": {"page_weight": 0.03, "row_weight": 0.001, "bias": 1.0},
    }

    def __init__(self, learning_rate: float = 0.1, weights_path: Optional[str] = None):
        self.learning_rate = learning_rate
        self.weights: Dict[str, Dict[str, float]] = {}
        self.query_count = 0
        self.total_error = 0.0

        # Load weights or use defaults
        if weights_path and os.path.exists(weights_path):
            self.load_weights(weights_path)
        else:
            self.weights = {k: dict(v) for k, v in self.DEFAULT_WEIGHTS.items()}

    def estimate_cost(self, plan_name: str, pages: int, rows: int, selectivity: float = 1.0) -> float:
        """Estimate query execution cost in milliseconds."""
        w = self.weights.get(plan_name, self.DEFAULT_WEIGHTS.get("FullScan"))
        effective_rows = rows * selectivity
        cost = (w["page_weight"] * pages +
                w["row_weight"] * effective_rows +
                w["bias"])
        return max(cost, 0.01)

    def update(self, plan_name: str, pages: int, rows: int, selectivity: float,
               actual_time_ms: float):
        """Update weights based on actual execution time (online learning).
        
        Uses exponential moving average — no backprop library needed.
        The gradient is simply the error scaled by the feature value.
        """
        predicted = self.estimate_cost(plan_name, pages, rows, selectivity)
        error = actual_time_ms - predicted
        self.total_error += abs(error)
        self.query_count += 1

        if plan_name not in self.weights:
            return

        w = self.weights[plan_name]
        effective_rows = rows * selectivity
        lr = self.learning_rate

        # Simple online gradient step:
        #   w_i += lr * error * feature_i / (1 + |feature_i|)
        # The denominator prevents large features from dominating
        if pages > 0:
            w["page_weight"] += lr * error * pages / (1.0 + pages)
        if effective_rows > 0:
            w["row_weight"] += lr * error * effective_rows / (1.0 + effective_rows)
        w["bias"] += lr * error * 0.1

        # Clamp weights to reasonable ranges
        w["page_weight"] = max(0.001, min(w["page_weight"], 10.0))
        w["row_weight"] = max(0.0001, min(w["row_weight"], 1.0))
        w["bias"] = max(0.0, min(w["bias"], 100.0))

    def select_best_plan(self, candidates: list) -> Tuple[str, float]:
        """Select the plan with lowest estimated cost.
        
        candidates: list of dicts with keys: name, pages, rows, selectivity
        """
        best = None
        best_cost = float('inf')
        for c in candidates:
            cost = self.estimate_cost(c["name"], c["pages"], c["rows"], c.get("selectivity", 1.0))
            if cost < best_cost:
                best_cost = cost
                best = c
        return (best["name"] if best else "FullScan"), best_cost

    @property
    def mean_absolute_error(self) -> float:
        if self.query_count == 0:
            return 0.0
        return self.total_error / self.query_count

    def save_weights(self, path: str):
        data = {
            "weights": self.weights,
            "query_count": self.query_count,
            "total_error": self.total_error,
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def load_weights(self, path: str):
        with open(path, 'r') as f:
            data = json.load(f)
        self.weights = data.get("weights", self.weights)
        self.query_count = data.get("query_count", 0)
        self.total_error = data.get("total_error", 0.0)
