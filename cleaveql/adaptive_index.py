"""Adaptive Indexing — tracks un-indexed field query frequency and auto-suggests indexes.

Monitors which fields are queried most frequently and suggests creating
indexes when the query count exceeds a configurable threshold.
"""
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set, Tuple


class AdaptiveIndexSuggester:
    """Monitors query patterns and suggests indexes for frequently queried fields.
    
    The basic insight: if a field is queried N times without an index,
    creating one would likely improve performance.
    """

    DEFAULT_THRESHOLD = 10  # Suggest after 10 queries on an un-indexed field

    def __init__(self, threshold: int = DEFAULT_THRESHOLD,
                 existing_indexes: Optional[Set[str]] = None):
        self.threshold = threshold
        self.existing_indexes: Set[str] = existing_indexes or set()
        self.query_counts: Counter = Counter()  # "bucket:field" -> count
        self.query_patterns: Dict[str, Counter] = defaultdict(Counter)  # bucket -> {field: count}
        self.suggestions_given: Set[str] = set()  # Already suggested, don't repeat

    def record_query(self, bucket: str, fields: List[str]):
        """Record that a query used these fields in predicates/filters."""
        for field in fields:
            key = f"{bucket}:{field}"
            self.query_counts[key] += 1
            self.query_patterns[bucket][field] += 1

    def check_suggestions(self) -> List[Dict]:
        """Check if any fields have crossed the threshold for index suggestion.
        
        Returns list of suggestion dicts with:
        - bucket, field, query_count, priority (high/medium/low)
        """
        suggestions = []
        for key, count in self.query_counts.most_common():
            if key in self.existing_indexes:
                continue
            if key in self.suggestions_given:
                continue
            if count >= self.threshold:
                bucket, field = key.split(":", 1)
                priority = "high" if count >= self.threshold * 3 else \
                           "medium" if count >= self.threshold * 1.5 else "low"
                suggestions.append({
                    "bucket": bucket,
                    "field": field,
                    "query_count": count,
                    "priority": priority,
                    "suggestion": f"index {bucket} on ({field})",
                })
                self.suggestions_given.add(key)

        # Sort by query count descending
        suggestions.sort(key=lambda s: s["query_count"], reverse=True)
        return suggestions

    def get_hint(self, bucket: str, field: str) -> Optional[str]:
        """Get a hint for the REPL if a field is nearing the threshold."""
        key = f"{bucket}:{field}"
        count = self.query_counts.get(key, 0)
        if key in self.existing_indexes:
            return None
        if count >= self.threshold * 0.7:  # 70% of threshold
            remaining = self.threshold - count
            if remaining > 0:
                return f"Hint: '{field}' queried {count} times. {remaining} more before index suggestion."
            else:
                return f"Suggestion: create an index on '{bucket}' for field '{field}' ({count} queries)"
        return None

    def register_index(self, bucket: str, field: str):
        """Mark a field as indexed (suppresses future suggestions)."""
        key = f"{bucket}:{field}"
        self.existing_indexes.add(key)

    def get_statistics(self) -> Dict:
        """Return query pattern statistics."""
        return {
            "total_queries_tracked": sum(self.query_counts.values()),
            "unique_field_patterns": len(self.query_counts),
            "indexed_fields": len(self.existing_indexes),
            "suggestions_given": len(self.suggestions_given),
            "top_unindexed": [
                {"field": k, "count": v}
                for k, v in self.query_counts.most_common(10)
                if k not in self.existing_indexes
            ],
        }

    def format_suggestions(self, suggestions: List[Dict]) -> str:
        """Format suggestions for REPL display."""
        if not suggestions:
            return "No index suggestions at this time."
        lines = ["Index Suggestions:", ""]
        for s in suggestions:
            lines.append(f"  [{s['priority'].upper():>6}] {s['suggestion']}  ({s['query_count']} queries)")
        return "\n".join(lines)
