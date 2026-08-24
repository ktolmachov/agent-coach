"""``rag.search`` adapter over the local vector store."""

from __future__ import annotations

from collections.abc import Mapping

from agent_coach.core.contracts import ToolAccess, ToolContext, ToolResult, ToolSpec
from agent_coach.retrieval.contracts import (
    DiplomaKnowledgeBase,
    Hit,
    RetrievalConfig,
    validate_top_k,
)
from agent_coach.retrieval.store import InMemoryCosineStore

ALLOWED_SEARCH_ARGS = frozenset({"query", "top_k"})


class LocalVectorRagTool:
    """ToolExecutionPort implementation for local-vector ``rag.search`` only."""

    def __init__(
        self,
        store: InMemoryCosineStore,
        knowledge_base: DiplomaKnowledgeBase,
        *,
        config: RetrievalConfig | None = None,
    ) -> None:
        self._store = store
        self._knowledge_base = knowledge_base
        self._config = config if config is not None else RetrievalConfig()

    def execute(
        self,
        tool: ToolSpec,
        args: Mapping[str, object],
        context: ToolContext,
    ) -> ToolResult:
        del context
        if tool.access is not ToolAccess.READ:
            return ToolResult.failure(
                "security: local-vector adapter refuses write-enabled tools",
                category="security",
            )
        if tool.name != "rag.search":
            return ToolResult.failure(
                "validation: local-vector adapter only executes rag.search",
                category="validation",
            )
        extra = sorted(str(key) for key in args if key not in ALLOWED_SEARCH_ARGS)
        if extra:
            return ToolResult.failure(
                "validation: unexpected field(s): " + ", ".join(extra),
                category="validation",
            )
        if (
            self._store.chunk_set_fingerprint
            != self._knowledge_base.chunk_set_fingerprint
        ):
            return ToolResult.failure(
                "validation: vector index does not match the knowledge base",
                category="validation",
            )
        if self._store.vector_dimensions != self._config.vector_dimensions:
            return ToolResult.failure(
                "validation: embedder dimensions do not match retrieval config",
                category="validation",
            )
        query = args.get("query")
        if not isinstance(query, str):
            return ToolResult.failure(
                "validation: query must be a string",
                category="validation",
            )
        bounded_query = query[: self._config.max_query_chars]
        raw_top_k = args.get("top_k", self._config.default_top_k)
        try:
            top_k = validate_top_k(raw_top_k, self._config)
            hits = self._store.search(
                bounded_query,
                top_k=top_k,
                threshold=self._config.score_threshold,
            )
        except ValueError as exc:
            return ToolResult.failure(str(exc), category="validation")
        return ToolResult.success(
            {
                "chunks": [_chunk_projection(hit) for hit in hits],
            },
            sources=[_source_projection(hit) for hit in hits],
            query=bounded_query,
            selected_chunk_ids=[hit.chunk.chunk_id for hit in hits],
            scores=[hit.score for hit in hits],
            threshold=self._config.score_threshold,
            corpus_version=self._knowledge_base.corpus_version,
            corpus_hash=self._knowledge_base.corpus_hash,
            index_fingerprint=self._store.index_fingerprint,
            adapter_profile="local_vector",
            hit_count=len(hits),
            excerpt="" if not hits else hits[0].chunk.text,
        )


def _chunk_projection(hit: Hit) -> dict[str, object]:
    return {
        "chunk_id": hit.chunk.chunk_id,
        "document_id": hit.chunk.document_id,
        "text": hit.chunk.text,
        "source": hit.chunk.source,
        "title": hit.chunk.title,
        "score": hit.score,
        "cite_index": hit.cite_index,
        "version": hit.chunk.version,
    }


def _source_projection(hit: Hit) -> dict[str, object]:
    return {
        "file_name": hit.chunk.source,
        "title": hit.chunk.title,
        "source": hit.chunk.source,
        "text": hit.chunk.text,
        "cite_index": hit.cite_index,
    }
