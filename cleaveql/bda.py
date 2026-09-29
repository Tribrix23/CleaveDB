"""Bond Discovery Attention (BDA) — field-key overlap scoring and bond suggestions.

Analyzes document schemas across buckets to discover potential bond
relationships by scoring field-key overlaps and naming patterns.
"""
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple


class BondDiscoveryAttention:
    """Discovers potential bonds between buckets by analyzing field patterns.
    
    Scoring is based on:
    1. Field-key overlap: if bucket A has field 'customer_id' and bucket B 
       has documents keyed by IDs that look like customer IDs, that's a bond signal.
    2. Naming convention: fields ending in '_id', '_key', '_ref' are foreign key candidates.
    3. Value overlap: if field values in A appear as document IDs in B, strong signal.
    """

    # Patterns that suggest a field is a foreign key reference
    FK_PATTERNS = [
        re.compile(r'(.+)_id$', re.IGNORECASE),
        re.compile(r'(.+)_key$', re.IGNORECASE),
        re.compile(r'(.+)_ref$', re.IGNORECASE),
        re.compile(r'(.+)Id$'),          # camelCase
        re.compile(r'(.+)Key$'),
        re.compile(r'^fk_(.+)$', re.IGNORECASE),
    ]

    def __init__(self):
        self.bucket_schemas: Dict[str, Dict[str, str]] = {}  # bucket -> {field: type}
        self.bucket_sample_ids: Dict[str, List[str]] = {}     # bucket -> sample doc IDs
        self.field_sample_values: Dict[str, Dict[str, List[str]]] = {}  # bucket -> {field: [sample values]}

    def register_bucket(self, bucket_name: str, schema: Dict[str, str],
                        sample_ids: List[str] = None,
                        sample_values: Dict[str, List[str]] = None):
        """Register a bucket's schema and sample data for analysis."""
        self.bucket_schemas[bucket_name] = schema
        if sample_ids:
            self.bucket_sample_ids[bucket_name] = sample_ids
        if sample_values:
            self.field_sample_values[bucket_name] = sample_values

    def suggest_bonds(self, min_score: float = 0.3) -> List[Dict]:
        """Analyze all registered buckets and suggest bonds.
        
        Returns list of suggestions, each with:
        - from_bucket, from_field, to_bucket
        - score (0.0 to 1.0)
        - reason: human-readable explanation
        - suggested_strength: soft/firm/strict based on confidence
        """
        suggestions = []
        buckets = list(self.bucket_schemas.keys())

        for src_bucket in buckets:
            schema = self.bucket_schemas[src_bucket]
            for field_name, field_type in schema.items():
                # Check naming patterns
                fk_match = self._match_fk_pattern(field_name)
                if not fk_match:
                    continue

                target_name = fk_match
                # Try to find a matching target bucket
                for dst_bucket in buckets:
                    if dst_bucket == src_bucket:
                        continue

                    score, reasons = self._score_bond(
                        src_bucket, field_name, field_type,
                        dst_bucket, target_name
                    )

                    if score >= min_score:
                        strength = "strict" if score > 0.8 else "firm" if score > 0.5 else "soft"
                        suggestions.append({
                            "from_bucket": src_bucket,
                            "from_field": field_name,
                            "to_bucket": dst_bucket,
                            "score": round(score, 3),
                            "reason": "; ".join(reasons),
                            "suggested_strength": strength,
                            "suggested_name": f"{src_bucket}_{field_name}_to_{dst_bucket}",
                        })

        # Sort by score descending
        suggestions.sort(key=lambda x: x["score"], reverse=True)
        return suggestions

    def _match_fk_pattern(self, field_name: str) -> Optional[str]:
        """Check if field name matches a foreign key pattern. Returns target name if so."""
        for pattern in self.FK_PATTERNS:
            m = pattern.match(field_name)
            if m:
                return m.group(1).lower()
        return None

    def _score_bond(self, src_bucket: str, field_name: str, field_type: str,
                    dst_bucket: str, target_name: str) -> Tuple[float, List[str]]:
        """Score the likelihood of a bond between src.field and dst bucket."""
        score = 0.0
        reasons = []

        # 1. Name match: target_name matches or is contained in dst_bucket name
        dst_name_lower = dst_bucket.lower().split('/')[-1]  # Get last path component
        if target_name == dst_name_lower or target_name + 's' == dst_name_lower:
            score += 0.4
            reasons.append(f"field '{field_name}' name matches bucket '{dst_bucket}'")
        elif target_name in dst_name_lower:
            score += 0.2
            reasons.append(f"field '{field_name}' name partially matches '{dst_bucket}'")

        # 2. Type match: string/id fields are more likely foreign keys
        if field_type in ('string', 'str', 'id'):
            score += 0.1
            reasons.append("field type is string/id")

        # 3. Value overlap: check if sample values appear in target's sample IDs
        src_values = (self.field_sample_values.get(src_bucket, {}).get(field_name, []))
        dst_ids = self.bucket_sample_ids.get(dst_bucket, [])
        if src_values and dst_ids:
            overlap = len(set(src_values) & set(dst_ids))
            overlap_ratio = overlap / max(len(src_values), 1)
            if overlap_ratio > 0:
                score += min(overlap_ratio * 0.5, 0.4)
                reasons.append(f"{overlap}/{len(src_values)} values found in target IDs ({overlap_ratio:.0%})")

        return score, reasons

    def format_suggestions(self, suggestions: List[Dict]) -> str:
        """Format suggestions as a readable table."""
        if not suggestions:
            return "No bond suggestions found."

        lines = ["Bond Suggestions:", ""]
        lines.append(f"{'Score':>6}  {'Strength':>8}  {'From':30s}  {'To':20s}  Reason")
        lines.append("-" * 100)
        for s in suggestions:
            from_str = f"{s['from_bucket']}.{s['from_field']}"
            lines.append(
                f"{s['score']:6.3f}  {s['suggested_strength']:>8}  {from_str:30s}  {s['to_bucket']:20s}  {s['reason']}"
            )
        return "\n".join(lines)
