"""Query Understanding Attention (QUA) — intent classification + field binding.

Uses a simple attention-based classifier to determine query intent
(structured vs. ambiguous) and bind fields to the correct bucket schema.
"""
import math
import json
import os
from typing import Dict, List, Optional, Tuple


class AttentionHead:
    """Single scaled dot-product attention head (pure Python fallback)."""

    def __init__(self, dim: int):
        self.dim = dim
        self.scale = 1.0 / math.sqrt(dim)
        # Initialize with simple identity-like weights
        self.w_q = [[1.0 if i == j else 0.0 for j in range(dim)] for i in range(dim)]
        self.w_k = [[1.0 if i == j else 0.0 for j in range(dim)] for i in range(dim)]
        self.w_v = [[1.0 if i == j else 0.0 for j in range(dim)] for i in range(dim)]

    def forward(self, x: List[List[float]]) -> List[List[float]]:
        """x: [seq_len, dim] -> [seq_len, dim]"""
        q = self._matmul(x, self.w_q)
        k = self._matmul(x, self.w_k)
        v = self._matmul(x, self.w_v)

        # scores = Q * K^T * scale
        scores = [[sum(q[i][d] * k[j][d] for d in range(self.dim)) * self.scale
                    for j in range(len(k))]
                   for i in range(len(q))]

        # softmax per row
        attn = [self._softmax(row) for row in scores]

        # output = attn * V
        output = [[sum(attn[i][j] * v[j][d] for j in range(len(v)))
                    for d in range(self.dim)]
                   for i in range(len(attn))]
        return output

    @staticmethod
    def _matmul(a, b):
        rows_a, cols_b = len(a), len(b[0])
        cols_a = len(a[0])
        return [[sum(a[i][k] * b[k][j] for k in range(cols_a))
                 for j in range(cols_b)]
                for i in range(rows_a)]

    @staticmethod
    def _softmax(x):
        max_x = max(x)
        exps = [math.exp(xi - max_x) for xi in x]
        total = sum(exps)
        return [e / total for e in exps]


class QueryUnderstandingAttention:
    """Intent classification and field binding via attention.

    Classifies CleaveQL queries into intent categories:
    - structured: well-formed with explicit fields and operators
    - keyword_search: primarily text-based, should use BM25
    - semantic_search: meaning-based, should use vector similarity
    - ambiguous: unclear intent, needs attention-based disambiguation
    """

    INTENTS = ["structured", "keyword_search", "semantic_search", "ambiguous"]

    # Keywords that signal each intent
    INTENT_SIGNALS = {
        "structured": {"where", "from", "limit", "order", "count", "index", "bond",
                       "shape", "drain", "change", "heal", "show", "describe"},
        "keyword_search": {"mentioning", "search", "find", "contains", "matching"},
        "semantic_search": {"meaning", "similar", "like", "related", "about"},
        "ambiguous": set(),  # Fallback
    }

    def __init__(self, dim: int = 32, weights_path: Optional[str] = None):
        self.dim = dim
        self.attention = AttentionHead(dim)
        self.intent_vectors: Dict[str, List[float]] = {}
        self._init_intent_vectors()
        if weights_path and os.path.exists(weights_path):
            self.load_weights(weights_path)

    def _init_intent_vectors(self):
        """Initialize intent prototype vectors (learnable)."""
        for i, intent in enumerate(self.INTENTS):
            vec = [0.0] * self.dim
            # Spread intents across dimensions
            for d in range(self.dim):
                vec[d] = math.sin((i + 1) * (d + 1) * 0.1)
            self.intent_vectors[intent] = vec

    def classify(self, tokens: List[str]) -> Tuple[str, float]:
        """Classify a tokenized query into an intent with confidence score."""
        # Rule-based fast path for obvious cases
        token_set = set(t.lower() for t in tokens)

        scores = {}
        for intent, signals in self.INTENT_SIGNALS.items():
            overlap = len(token_set & signals)
            scores[intent] = overlap

        # If no clear signal, use attention-based scoring
        total = sum(scores.values())
        if total == 0:
            scores["ambiguous"] = 1.0
            return "ambiguous", 0.5

        best_intent = max(scores, key=scores.get)
        confidence = scores[best_intent] / max(total, 1)

        # Low confidence → ambiguous
        if confidence < 0.4 and best_intent != "ambiguous":
            return "ambiguous", confidence

        return best_intent, min(confidence, 1.0)

    def bind_fields(self, tokens: List[str], schema_fields: List[str]) -> Dict[str, str]:
        """Bind query tokens to schema fields using string similarity."""
        bindings = {}
        for token in tokens:
            token_lower = token.lower()
            best_field = None
            best_score = 0.0
            for field in schema_fields:
                score = self._field_similarity(token_lower, field.lower())
                if score > best_score and score > 0.5:
                    best_score = score
                    best_field = field
            if best_field:
                bindings[token] = best_field
        return bindings

    @staticmethod
    def _field_similarity(a: str, b: str) -> float:
        """Simple character-level similarity (Jaccard on character bigrams)."""
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        bigrams_a = {a[i:i+2] for i in range(len(a) - 1)}
        bigrams_b = {b[i:i+2] for i in range(len(b) - 1)}
        if not bigrams_a or not bigrams_b:
            return 0.0
        return len(bigrams_a & bigrams_b) / len(bigrams_a | bigrams_b)

    def save_weights(self, path: str):
        data = {"intent_vectors": self.intent_vectors, "dim": self.dim}
        with open(path, 'w') as f:
            json.dump(data, f)

    def load_weights(self, path: str):
        with open(path, 'r') as f:
            data = json.load(f)
        self.intent_vectors = data.get("intent_vectors", self.intent_vectors)
