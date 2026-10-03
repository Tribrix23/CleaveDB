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

    def explain_cost(self, stmt, total_docs: int, available_indexes: list):
        """Generates a structured query cost breakdown and suggestions."""
        bucket = getattr(stmt, "bucket", "")
        where = getattr(stmt, "where", None)
        order_by = getattr(stmt, "order_by", None)
        sort_fields = [order_by] if order_by else []
        limit = getattr(stmt, "limit", None)
        
        where_fields = []
        if where:
            for p in getattr(where, "predicates", []):
                if hasattr(p, "field"):
                    where_fields.append(p.field)
                    
        has_applicable_index = False
        for idx in available_indexes:
            fields = idx.get("fields", [])
            # Check if index fields cover ANY of the where fields
            if any(f in fields for f in where_fields):
                has_applicable_index = True
                break
                
        scan_type = "INDEX_SCAN" if has_applicable_index else "FULL_BUCKET_SCAN"
        
        # Estimate selectivity
        selectivity = 1.0
        if where:
            for p in getattr(where, "predicates", []):
                op = getattr(p, "op", "=")
                if op == "=":
                    selectivity *= 0.12
                else:
                    selectivity *= 0.4
        
        selectivity = min(1.0, max(0.001, selectivity))
        if not where:
            selectivity = 1.0
            
        docs_after = int(total_docs * selectivity)
        
        index_covers_sort = False
        if has_applicable_index:
            for idx in available_indexes:
                fields = idx.get("fields", [])
                if any(f in fields for f in where_fields):
                    if all(sf in fields for sf in sort_fields):
                        index_covers_sort = True
                        break
        sort_in_memory = len(sort_fields) > 0 and not index_covers_sort
        
        # Calculate cost
        estimated_ms = 0.0
        pages = max(1, total_docs // 20)  # assume 20 docs per page
        
        if scan_type == "FULL_BUCKET_SCAN":
            estimated_ms += self.estimate_scan_cost(pages, total_docs)
            estimated_docs_scanned = total_docs
        else:
            estimated_ms += self.estimate_index_cost(3, docs_after)  # assume depth 3
            estimated_docs_scanned = max(1, int(total_docs * selectivity * 1.5))
            
        if sort_in_memory:
            estimated_ms += self.estimate_sort_cost(docs_after)
            
        suggestions = []
        if (not has_applicable_index and where_fields) or sort_in_memory:
            needed_fields = where_fields.copy()
            for sf in sort_fields:
                if sf not in needed_fields:
                    needed_fields.append(sf)
                    
            if not has_applicable_index:
                reason = "to avoid full scan" + (" and eliminate in-memory sort" if sort_in_memory else "")
                suggestions.append(f"Create INDEX {bucket} ON ({', '.join(needed_fields)}) {reason}")
            elif sort_in_memory:
                suggestions.append(f"Create compound INDEX {bucket} ON ({', '.join(needed_fields)}) to eliminate in-memory sort")
            
        if not limit and (total_docs > 1000 or sort_in_memory):
            suggestions.append("Add LIMIT to cap memory usage")
            
        if not suggestions:
            suggestions.append("Query is optimal")
            
        return {
            "scan_type": scan_type,
            "estimated_docs_scanned": estimated_docs_scanned,
            "filter_selectivity": round(selectivity, 3),
            "docs_after_filter": docs_after,
            "sort_in_memory": sort_in_memory,
            "has_applicable_index": has_applicable_index,
            "estimated_ms": max(1, int(estimated_ms)),
            "suggestions": suggestions
        }
