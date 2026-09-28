class CostModel:
    def __init__(self):
        # Constants calibrated against Windows SSD NVMe benchmarks
        self.page_read_cost = 0.05  # ms per page
        self.row_eval_cost = 0.001  # ms per row

    def estimate_scan_cost(self, num_pages, num_rows):
        return (num_pages * self.page_read_cost) + (num_rows * self.row_eval_cost)

    def estimate_index_cost(self, index_depth, expected_matches):
        # B-Tree traversal cost + fetching matched pages
        io_cost = (index_depth + expected_matches) * self.page_read_cost
        cpu_cost = expected_matches * self.row_eval_cost
        return io_cost + cpu_cost

    def select_best_plan(self, plans):
        # Volcano executor style plan selection
        best_plan = None
        lowest_cost = float('inf')
        for plan in plans:
            cost = plan.estimate_cost(self)
            if cost < lowest_cost:
                lowest_cost = cost
                best_plan = plan
        return best_plan
