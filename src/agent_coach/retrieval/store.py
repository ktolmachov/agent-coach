"""Bounded in-memory cosine index."""

from __future__ import annotations

import math
from collections.abc import Sequence

from agent_coach.retrieval.contracts import (
    DISTINCTIVE_TOKEN_CHARS,
    Chunk,
    EmbeddingPort,
    Hit,
    RetrievalConfig,
    chunks_fingerprint,
    round_score,
    validate_top_k,
    vector_index_fingerprint,
)
from agent_coach.retrieval.vectorizer import HashedNgramEmbedding, content_tokens


class InMemoryCosineStore:
    """Process-local cosine store with deterministic rebuilds and tie order.

    Scores are true cosine similarity in ``[-1.0, 1.0]``: the store divides the
    dot product by both L2 norms, so it does not assume a unit embedder.
    Hits below the caller threshold are dropped on every relevance branch,
    including title and rare-token support. Homonym overlaps of short generic
    tokens are not promoted.
    """

    def __init__(
        self,
        embedder: EmbeddingPort | None = None,
        *,
        config: RetrievalConfig | None = None,
    ) -> None:
        self._config = config if config is not None else RetrievalConfig()
        self._embedder = (
            embedder
            if embedder is not None
            else HashedNgramEmbedding(dimensions=self._config.vector_dimensions)
        )
        if self._embedder.dimensions != self._config.vector_dimensions:
            raise ValueError(
                "validation: embedder dimensions do not match retrieval config"
            )
        self._rows: tuple[tuple[Chunk, tuple[float, ...]], ...] = ()
        self._chunk_set_fingerprint = chunks_fingerprint(())
        self._index_fingerprint = vector_index_fingerprint(
            (),
            (),
            dimensions=self._embedder.dimensions,
        )

    @property
    def chunk_set_fingerprint(self) -> str:
        """Return the chunk-set identity of the currently indexed notes."""

        return self._chunk_set_fingerprint

    @property
    def index_fingerprint(self) -> str:
        """Return the identity of the built vector index, including vectors."""

        return self._index_fingerprint

    @property
    def vector_dimensions(self) -> int:
        """Return the embedder width bound into this index."""

        return self._embedder.dimensions

    def build(self, chunks: Sequence[Chunk]) -> None:
        if len(chunks) > self._config.max_corpus_chunks:
            raise ValueError("validation: corpus exceeds the trusted chunk bound")
        seen: set[str] = set()
        ordered = sorted(chunks, key=lambda chunk: (chunk.document_id, chunk.chunk_id))
        rows: list[tuple[Chunk, tuple[float, ...]]] = []
        for chunk in ordered:
            if chunk.chunk_id in seen:
                raise ValueError(f"validation: duplicate chunk_id {chunk.chunk_id!r}")
            if not chunk.text.strip():
                raise ValueError(f"validation: empty chunk text {chunk.chunk_id!r}")
            seen.add(chunk.chunk_id)
            vector = self._embedder.embed(_chunk_embedding_text(chunk))
            if len(vector) != self._embedder.dimensions:
                raise ValueError("validation: embedding width does not match embedder")
            if not all(
                isinstance(value, float | int)
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in vector
            ):
                raise ValueError("validation: embedding values must be finite")
            rows.append((chunk, tuple(float(value) for value in vector)))
        indexed_chunks = tuple(chunk for chunk, _vector in rows)
        indexed_vectors = tuple(vector for _chunk, vector in rows)
        chunk_set_fingerprint = chunks_fingerprint(indexed_chunks)
        index_fingerprint = vector_index_fingerprint(
            indexed_chunks,
            indexed_vectors,
            dimensions=self._embedder.dimensions,
        )
        self._rows = tuple(rows)
        self._chunk_set_fingerprint = chunk_set_fingerprint
        self._index_fingerprint = index_fingerprint

    def size(self) -> int:
        return len(self._rows)

    def fingerprint(self) -> tuple[tuple[str, str, tuple[float, ...]], ...]:
        """Return a deterministic index snapshot for idempotence checks."""

        return tuple(
            (chunk.document_id, chunk.chunk_id, vector) for chunk, vector in self._rows
        )

    def search(
        self,
        query: str,
        *,
        top_k: int,
        threshold: float,
    ) -> tuple[Hit, ...]:
        bound_top_k = validate_top_k(top_k, self._config)
        if (
            not isinstance(threshold, float | int)
            or isinstance(threshold, bool)
            or not math.isfinite(float(threshold))
            or not 0.0 <= float(threshold) <= 1.0
        ):
            raise ValueError(
                "validation: threshold must be a finite value in [0.0, 1.0]"
            )
        query_vector = self._embedder.embed(query)
        query_tokens = content_tokens(query)
        if _is_zero_vector(query_vector) or not query_tokens:
            return ()
        ranked: list[tuple[float, str, str, Chunk]] = []
        bound_threshold = float(threshold)
        for chunk, vector in self._rows:
            score = _cosine(query_vector, vector)
            if not _is_relevant(
                score=score,
                query_tokens=query_tokens,
                chunk=chunk,
                threshold=bound_threshold,
                semantic_only_threshold=self._config.semantic_only_threshold,
                min_lexical_overlap=self._config.min_lexical_overlap,
            ):
                continue
            ranked.append((score, chunk.document_id, chunk.chunk_id, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        return tuple(
            Hit(
                chunk=chunk,
                score=round_score(score, decimals=self._config.score_decimals),
                cite_index=index,
            )
            for index, (score, _document_id, _chunk_id, chunk) in enumerate(
                ranked[:bound_top_k],
                start=1,
            )
        )


def _chunk_embedding_text(chunk: Chunk) -> str:
    return f"{chunk.title} {chunk.text}"


def _is_relevant(
    *,
    score: float,
    query_tokens: frozenset[str],
    chunk: Chunk,
    threshold: float,
    semantic_only_threshold: float,
    min_lexical_overlap: int,
) -> bool:
    if not math.isfinite(score) or score < threshold:
        return False
    if score >= semantic_only_threshold:
        return True
    chunk_tokens = content_tokens(f"{chunk.title} {chunk.text}")
    title_tokens = content_tokens(chunk.title)
    overlap = query_tokens & chunk_tokens
    distinctive_overlap = frozenset(
        token
        for token in overlap
        if len(token) >= DISTINCTIVE_TOKEN_CHARS or token in title_tokens
    )
    if len(distinctive_overlap) < min_lexical_overlap:
        return False
    distinctive_query = frozenset(
        token for token in query_tokens if len(token) >= DISTINCTIVE_TOKEN_CHARS
    )
    unmatched = frozenset(
        token
        for token in distinctive_query - distinctive_overlap
        if not _is_prefix_of_any(token, distinctive_overlap)
    )
    return not (
        len(distinctive_query) >= 3
        and unmatched
        and score < semantic_only_threshold
    )


def _is_prefix_of_any(token: str, candidates: frozenset[str]) -> bool:
    return any(
        other != token and other.startswith(token)
        for other in candidates
    )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("validation: embedding widths do not match")
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    dot = math.fsum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )
    score = dot / (left_norm * right_norm)
    if score > 1.0:
        return 1.0
    if score < -1.0:
        return -1.0
    return score


def _is_zero_vector(vector: Sequence[float]) -> bool:
    return all(value == 0.0 for value in vector)
