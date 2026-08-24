"""Deterministic hashed n-gram embedder. No model download and no network."""

from __future__ import annotations

import hashlib
import math
import re

from agent_coach.retrieval.contracts import DEFAULT_VECTOR_DIMENSIONS

_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "by",
        "does",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "about",
        "can",
        "define",
        "describe",
        "explain",
        "what",
        "why",
        "with",
    }
)
_MIN_TOKEN_CHARS = 4


class HashedNgramEmbedding:
    """Signed hashing trick over Unicode word and character n-grams.

    Vectors are L2-normalized as a convenience of this embedder. The vector
    store still computes a true cosine, so a later unnormalized embedder stays
    in ``[-1.0, 1.0]``. The implementation is network-free and uses only
    ``hashlib.sha256``.
    """

    def __init__(self, *, dimensions: int = DEFAULT_VECTOR_DIMENSIONS) -> None:
        if dimensions < 8:
            raise ValueError("embedding dimensions must be at least 8")
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self._dimensions
        normalized = " ".join(str(text or "").casefold().split())
        if not normalized:
            return tuple(vector)
        for token, weight in _features(normalized):
            bucket, sign = _signed_bucket(token, self._dimensions)
            vector[bucket] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(value / norm for value in vector)


def content_tokens(text: str) -> frozenset[str]:
    """Return distinctive Unicode tokens used by the lexical overlap gate."""

    return frozenset(
        token
        for token in _TOKEN_PATTERN.findall(str(text or "").casefold())
        if len(token) >= _MIN_TOKEN_CHARS and token not in _STOP_WORDS
    )


def _features(text: str) -> list[tuple[str, float]]:
    words = [
        token
        for token in _TOKEN_PATTERN.findall(text)
        if len(token) > 2 and token not in _STOP_WORDS
    ]
    features: list[tuple[str, float]] = [(f"u:{word}", 1.0) for word in words]
    features.extend(
        (f"b:{left}_{right}", 0.9)
        for left, right in zip(words, words[1:], strict=False)
    )
    compact = "".join(words)
    if len(compact) >= 3:
        features.extend(
            (f"c:{compact[index:index + 3]}", 0.08)
            for index in range(len(compact) - 2)
        )
    return features


def _signed_bucket(token: str, dimensions: int) -> tuple[int, float]:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") % dimensions
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    return bucket, sign
