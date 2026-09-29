import json

class Formatter:
    def format_table(self, results: list, fields: list = None) -> str:
        if not results:
            return "No results."
        if not fields:
            fields_set = set()
            for r in results:
                fields_set.update(r.keys())
            fields = list(fields_set)

        str_results = [{k: str(v.get(k, '')) for k in fields} for v in results]
        col_widths = {k: max(len(k), max([len(r[k]) for r in str_results] + [0])) for k in fields}
        
        header = " | ".join(k.ljust(col_widths[k]) for k in fields)
        separator = "-+-".join("-" * col_widths[k] for k in fields)
        
        rows = [" | ".join(r[k].ljust(col_widths[k]) for k in fields) for r in str_results]
        
        return "\n".join([header, separator] + rows)

    def format_count(self, count: int) -> str:
        return f"Count: {count}"

    def format_explain(self, plan_info: dict) -> str:
        return json.dumps(plan_info, indent=2)

    def format_json(self, data) -> str:
        return json.dumps(data, indent=2)

    def format_error(self, error) -> str:
        return f"Error: {error}"
