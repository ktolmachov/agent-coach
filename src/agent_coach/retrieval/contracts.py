"""Retrieval-layer contracts kept outside Agent Core.

Core continues to see only ``ToolExecutionPort`` and ``ToolResult``. Embedding
and vector-store ports live here so a later provider embedder can replace the
offline hasher without turning Core into a RAG framework.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

DIPLOMA_KB_SCHEMA_VERSION = "agent-coach-diploma-kb/1.0.0"
DEFAULT_VECTOR_DIMENSIONS = 384
DEFAULT_SCORE_THRESHOLD = 0.20
DEFAULT_TOP_K = 4
MIN_TOP_K = 1
MAX_TOP_K = 8
MAX_QUERY_CHARS = 500
MAX_CORPUS_CHUNKS = 256
MAX_CHUNK_TEXT_CHARS = 2000
MAX_TITLE_CHARS = 160
MAX_SOURCE_CHARS = 80
MAX_IDENTIFIER_CHARS = 80
MIN_LEXICAL_OVERLAP = 1
DISTINCTIVE_TOKEN_CHARS = 6
DEFAULT_SEMANTIC_ONLY_THRESHOLD = 0.40
SCORE_DECIMALS = 6
REQUIRED_FALSE_PROVENANCE_FLAGS = (
    "contains_production_data",
    "contains_credentials",
    "contains_learner_data",
    "contains_hometutor_runtime_dependency",
)
REQUIRED_CORPUS_CLASSIFICATION = "synthetic_public_review_corpus"
ALLOWED_PROVENANCE_KEYS = frozenset(
    {
        "classification",
        "source",
        *REQUIRED_FALSE_PROVENANCE_FLAGS,
    }
)


@dataclass(frozen=True)
class RetrievalConfig:
    """Trusted retrieval limits. Model-supplied args cannot set the threshold."""

    default_top_k: int = DEFAULT_TOP_K
    min_top_k: int = MIN_TOP_K
    max_top_k: int = MAX_TOP_K
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    max_query_chars: int = MAX_QUERY_CHARS
    vector_dimensions: int = DEFAULT_VECTOR_DIMENSIONS
    max_corpus_chunks: int = MAX_CORPUS_CHUNKS
    max_chunk_text_chars: int = MAX_CHUNK_TEXT_CHARS
    max_title_chars: int = MAX_TITLE_CHARS
    max_source_chars: int = MAX_SOURCE_CHARS
    min_lexical_overlap: int = MIN_LEXICAL_OVERLAP
    semantic_only_threshold: float = DEFAULT_SEMANTIC_ONLY_THRESHOLD
    score_decimals: int = SCORE_DECIMALS

    def __post_init__(self) -> None:
        _require_int("min_top_k", self.min_top_k, minimum=1)
        _require_int("max_top_k", self.max_top_k, minimum=1)
        _require_int("default_top_k", self.default_top_k, minimum=1)
        if not self.min_top_k <= self.default_top_k <= self.max_top_k:
            raise ValueError("validation: top_k bounds are inconsistent")
        _require_int("max_query_chars", self.max_query_chars, minimum=1)
        _require_int("vector_dimensions", self.vector_dimensions, minimum=8)
        _require_int("max_corpus_chunks", self.max_corpus_chunks, minimum=1)
        _require_int("max_chunk_text_chars", self.max_chunk_text_chars, minimum=1)
        _require_int("max_title_chars", self.max_title_chars, minimum=1)
        _require_int("max_source_chars", self.max_source_chars, minimum=1)
        _require_int("min_lexical_overlap", self.min_lexical_overlap, minimum=1)
        _require_int("score_decimals", self.score_decimals, minimum=0, maximum=12)
        if not isinstance(self.score_threshold, float | int) or isinstance(
            self.score_threshold, bool
        ):
            raise ValueError("validation: score_threshold must be a number")
        threshold = float(self.score_threshold)
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError("validation: score_threshold must be in [0.0, 1.0]")
        if not isinstance(self.semantic_only_threshold, float | int) or isinstance(
            self.semantic_only_threshold, bool
        ):
            raise ValueError("validation: semantic_only_threshold must be a number")
        semantic_only = float(self.semantic_only_threshold)
        if not math.isfinite(semantic_only) or not 0.0 <= semantic_only <= 1.0:
            raise ValueError(
                "validation: semantic_only_threshold must be in [0.0, 1.0]"
            )
        if semantic_only <= threshold:
            raise ValueError(
                "validation: semantic_only_threshold must exceed score_threshold"
            )


@dataclass(frozen=True)
class Document:
    """Public synthetic document metadata."""

    document_id: str
    title: str
    source: str
    version: str
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """One indexed public excerpt."""

    document_id: str
    chunk_id: str
    title: str
    source: str
    text: str
    version: str
    provenance: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DeclaredQuery:
    """Frozen query used as executable retrieval evidence."""

    query_id: str
    query: str
    expected_chunk_id: str


@dataclass(frozen=True)
class Hit:
    """One bounded similarity match. Vectors are never attached."""

    chunk: Chunk
    score: float
    cite_index: int


@dataclass(frozen=True)
class DiplomaKnowledgeBase:
    """Loaded public corpus plus the declared D8 query set."""

    schema_version: str
    corpus_version: str
    provenance: Mapping[str, object]
    documents: tuple[Document, ...]
    chunks: tuple[Chunk, ...]
    declared_queries: tuple[DeclaredQuery, ...]
    declared_paraphrase_queries: tuple[DeclaredQuery, ...]
    declared_negative_queries: tuple[str, ...]
    raw_text: str
    corpus_hash: str
    chunk_set_fingerprint: str


@runtime_checkable
class EmbeddingPort(Protocol):
    """Numeric embedding boundary. Offline and later provider impls share it."""

    @property
    def dimensions(self) -> int:
        """Return the fixed vector width."""

    def embed(self, text: str) -> tuple[float, ...]:
        """Return one finite numeric vector. Empty text yields a zero vector."""


@runtime_checkable
class VectorStorePort(Protocol):
    """In-process similarity index. No filesystem or database writes."""

    def build(self, chunks: Sequence[Chunk]) -> None:
        """Replace the in-memory index. Repeated builds are idempotent."""

    def size(self) -> int:
        """Return the number of indexed chunks."""

    def search(
        self,
        query: str,
        *,
        top_k: int,
        threshold: float,
    ) -> tuple[Hit, ...]:
        """Return thresholded top-k hits with deterministic tie order."""


def round_score(score: float, *, decimals: int = SCORE_DECIMALS) -> float:
    """Return a documented finite cosine score with stable decimal width."""

    if not isinstance(score, float | int) or isinstance(score, bool):
        raise ValueError("score must be a finite number")
    value = float(score)
    if not math.isfinite(value):
        raise ValueError("score must be finite")
    if value < -1.0 or value > 1.0:
        raise ValueError("score must be in [-1.0, 1.0]")
    return float(f"{value:.{decimals}f}")


def validate_top_k(top_k: object, config: RetrievalConfig) -> int:
    """Fail closed when planner-supplied top_k is missing bounds."""

    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ValueError("validation: top_k must be an integer")
    if top_k < config.min_top_k or top_k > config.max_top_k:
        raise ValueError(
            "validation: top_k is outside the trusted "
            f"[{config.min_top_k}, {config.max_top_k}] bound"
        )
    return top_k


def chunks_fingerprint(chunks: Sequence[Chunk]) -> str:
    """Return a chunk-set identity over ids and texts, not the vector index."""

    payload = [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "text": chunk.text,
            "title": chunk.title,
            "source": chunk.source,
            "version": chunk.version,
        }
        for chunk in sorted(
            chunks, key=lambda item: (item.document_id, item.chunk_id)
        )
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def vector_index_fingerprint(
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
    *,
    dimensions: int,
) -> str:
    """Return the identity of a built vector index, including embeddings."""

    if len(chunks) != len(vectors):
        raise ValueError("validation: vector rows do not match the chunk set")
    payload = {
        "chunk_set": chunks_fingerprint(chunks),
        "dimensions": dimensions,
        "vectors": [
            [_canonical_float(value) for value in vector] for vector in vectors
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_float(value: object) -> str:
    if not isinstance(value, float | int) or isinstance(value, bool):
        raise ValueError("validation: embedding values must be numbers")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("validation: embedding values must be finite")
    return format(number, ".17g")


def _require_int(
    name: str,
    value: object,
    *,
    minimum: int,
    maximum: int | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"validation: {name} must be an integer")
    if value < minimum:
        raise ValueError(f"validation: {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"validation: {name} must be <= {maximum}")
