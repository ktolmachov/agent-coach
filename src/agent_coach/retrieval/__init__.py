"""Local vector memory adapters for the diploma demo."""

from agent_coach.retrieval.composition import (
    LocalVectorComposition,
    LocalVectorQuestionPlanner,
    advertised_local_vector_tools,
    build_local_vector_composition,
    build_local_vector_index,
)
from agent_coach.retrieval.contracts import (
    DIPLOMA_KB_SCHEMA_VERSION,
    Chunk,
    DeclaredQuery,
    DiplomaKnowledgeBase,
    Document,
    EmbeddingPort,
    Hit,
    RetrievalConfig,
    VectorStorePort,
    chunks_fingerprint,
)
from agent_coach.retrieval.corpus import load_diploma_knowledge_base
from agent_coach.retrieval.store import InMemoryCosineStore
from agent_coach.retrieval.tool_adapter import LocalVectorRagTool
from agent_coach.retrieval.vectorizer import HashedNgramEmbedding

__all__ = [
    "DIPLOMA_KB_SCHEMA_VERSION",
    "Chunk",
    "DeclaredQuery",
    "DiplomaKnowledgeBase",
    "Document",
    "EmbeddingPort",
    "HashedNgramEmbedding",
    "Hit",
    "InMemoryCosineStore",
    "LocalVectorComposition",
    "LocalVectorQuestionPlanner",
    "LocalVectorRagTool",
    "RetrievalConfig",
    "VectorStorePort",
    "advertised_local_vector_tools",
    "build_local_vector_composition",
    "build_local_vector_index",
    "chunks_fingerprint",
    "load_diploma_knowledge_base",
]
