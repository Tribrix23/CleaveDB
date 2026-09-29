"""Cost model for CleaveQL query optimizer.

Calibrated I/O + CPU cost model used to compare candidate query plans.
Integrates with statistics (histograms, HLL cardinality) for selectivity estimation.
"""
from typing import Dict, Optional


class CostModel:
    """Estimates query execution cost based on I/O pages read and CPU rows processed.
    
    cost = (pages_read × page_cost) + (rows_processed × row_cost)
    
    Default calibration values are based on typical NVMe SSD performance:
    - page_cost: 0.1 ms per 16KB page random read
    - row_cost: 0.001 ms per row processed (deserialize + evaluate)
    """

    def __init__(self, page_cost: float = 0.1, row_cost: float = 0.001):
        self.page_cost = page_cost
        self.row_cost = row_cost
        # Optional histogram/HLL-based selectivity overrides
        self._selectivity_cache: Dict[str, float] = {}

    def estimate_scan_cost(self, pages: int, rows: int) -> float:
        """Cost of a full sequential scan."""
        # Sequential reads are ~3× faster than random reads
        return (pages * self.page_cost * 0.33) + (rows * self.row_cost)

    def estimate_index_cost(self, index_depth: int, result_rows: int) -> float:
        """Cost of an index lookup: traverse B+Tree depth, then fetch result pages."""
        # B+Tree traversal: depth random reads
        traverse_cost = index_depth * self.page_cost
        # Result fetching: ~1 page per 100 results (assuming locality)
        result_pages = max(1, result_rows // 100)
        fetch_cost = result_pages * self.page_cost
        # CPU cost for processing results
        cpu_cost = result_rows * self.row_cost
        return traverse_cost + fetch_cost + cpu_cost

    def estimate_join_cost(self, left_rows: int, right_pages: int, selectivity: float = 0.01) -> float:
        """Cost of a nested-loop bond join."""
        # For each left row, do an index lookup on the right side
        lookups = int(left_rows * selectivity)
        return (lookups * self.page_cost * 3) + (lookups * self.row_cost)

    def estimate_sort_cost(self, rows: int) -> float:
        """Cost of an in-memory sort (for ORDER BY)."""
        import math
        if rows <= 1:
            return 0.0
        # O(n log n) comparison cost
        return rows * math.log2(rows) * self.row_cost * 0.5

    def set_selectivity(self, field: str, selectivity: float):
        """Override selectivity estimate for a specific field (from histogram stats)."""
        self._selectivity_cache[field] = selectivity

    def get_selectivity(self, field: str, default: float = 0.1) -> float:
        """Get selectivity estimate for a field. Returns default if unknown."""
        return self._selectivity_cache.get(field, default)

    def select_best_plan(self, plans: list):
        """Select the plan with lowest estimated cost."""
        if not plans:
            return None
        best = min(plans, key=lambda p: p.estimate_cost(self))
        return best

    def calibrate(self, measured_page_ms: float, measured_row_ms: float):
        """Recalibrate cost model from actual benchmark measurements."""
        self.page_cost = measured_page_ms
        self.row_cost = measured_row_ms
