"""Load the packaged public diploma knowledge base."""

from __future__ import annotations

import hashlib
import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from agent_coach.retrieval.contracts import (
    ALLOWED_PROVENANCE_KEYS,
    DIPLOMA_KB_SCHEMA_VERSION,
    REQUIRED_CORPUS_CLASSIFICATION,
    REQUIRED_FALSE_PROVENANCE_FLAGS,
    Chunk,
    DeclaredQuery,
    DiplomaKnowledgeBase,
    Document,
    RetrievalConfig,
    chunks_fingerprint,
)

DEFAULT_KB_RESOURCE = "diploma_knowledge_base.json"
_UNSAFE_CORPUS_PATTERN = re.compile(
    r"ignore previous|system prompt|developer message|reveal.*secret|"
    r"\b(?:api[_ -]?key|token|secret|password)\b\s*[:=]|"
    r"\bbearer\s+[A-Za-z0-9._\-+=/]{8,}|"
    r"\bauthorization\b\s*[:=]",
    flags=re.IGNORECASE,
)
_PUBLIC_SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")
_PUBLIC_PROVENANCE_SOURCE_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$"
)
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PRIVATE_PATH_PATTERN = re.compile(
    r"(?:file:///[^\s'\"<>|]+)"
    r"|(?:[A-Za-z]:[\\/][^\s'\"<>|]+)"
    r"|(?:\\\\[^\\/\s'\"<>|]+\\[^\s'\"<>|]+)"
    r"|(?:(?<![:/])/(?!/)[^\s'\"<>|]+)",
    flags=re.IGNORECASE,
)


def load_diploma_knowledge_base(
    path: Path | None = None,
    *,
    config: RetrievalConfig | None = None,
) -> DiplomaKnowledgeBase:
    """Load and validate the synthetic public corpus resource."""

    limits = config if config is not None else RetrievalConfig()
    raw_text = (
        resources.files("agent_coach.data")
        .joinpath(DEFAULT_KB_RESOURCE)
        .read_text(encoding="utf-8")
        if path is None
        else path.read_text(encoding="utf-8")
    )
    raw = json.loads(raw_text)
    if not isinstance(raw, dict):
        raise ValueError("diploma knowledge base must be a JSON object")
    schema_version = _require_text(
        raw.get("schema_version"),
        "schema_version",
        max_length=80,
    )
    if schema_version != DIPLOMA_KB_SCHEMA_VERSION:
        raise ValueError("unsupported diploma knowledge-base schema version")
    corpus_version = _require_text(
        raw.get("corpus_version"),
        "corpus_version",
        max_length=40,
    )
    provenance = _validate_provenance(raw.get("provenance"))
    raw_chunks = raw.get("chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ValueError("diploma knowledge base must contain chunks")
    chunks = tuple(_parse_chunk(item, provenance, limits) for item in raw_chunks)
    if len(chunks) > limits.max_corpus_chunks:
        raise ValueError("diploma knowledge base exceeds the trusted chunk bound")
    _reject_duplicate_ids([chunk.chunk_id for chunk in chunks], "chunk_id")
    documents = _documents_from_chunks(chunks, provenance)
    raw_queries = raw.get("declared_queries")
    if not isinstance(raw_queries, list):
        raise ValueError("declared queries must be an array")
    queries = tuple(_parse_query(item, limits) for item in raw_queries)
    if len(queries) < 8:
        raise ValueError("diploma knowledge base must declare at least 8 queries")
    raw_paraphrases = raw.get("declared_paraphrase_queries")
    if not isinstance(raw_paraphrases, list):
        raise ValueError("declared paraphrase queries must be an array")
    paraphrases = tuple(_parse_query(item, limits) for item in raw_paraphrases)
    if len(paraphrases) < 4:
        raise ValueError(
            "diploma knowledge base must declare at least 4 paraphrase queries"
        )
    _reject_duplicate_ids(
        [item.query_id for item in queries] + [item.query_id for item in paraphrases],
        "query_id",
    )
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    for query in (*queries, *paraphrases):
        if query.expected_chunk_id not in chunk_ids:
            raise ValueError(
                f"declared query {query.query_id!r} points at unknown chunk"
            )
    negatives = _parse_negative_queries(raw.get("declared_negative_queries"), limits)
    if len(negatives) < 4:
        raise ValueError(
            "diploma knowledge base must declare at least 4 negative queries"
        )
    positives = {item.query for item in queries} | {item.query for item in paraphrases}
    if positives & set(negatives):
        raise ValueError("negative queries must not duplicate declared queries")
    return DiplomaKnowledgeBase(
        schema_version=schema_version,
        corpus_version=corpus_version,
        provenance=provenance,
        documents=documents,
        chunks=chunks,
        declared_queries=queries,
        declared_paraphrase_queries=paraphrases,
        declared_negative_queries=negatives,
        raw_text=raw_text,
        corpus_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        chunk_set_fingerprint=chunks_fingerprint(chunks),
    )


def _validate_provenance(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("knowledge-base provenance must be an object")
    extra = sorted(str(key) for key in value if key not in ALLOWED_PROVENANCE_KEYS)
    if extra:
        raise ValueError(
            "knowledge-base provenance has unexpected field(s): " + ", ".join(extra)
        )
    classification = value.get("classification")
    if classification != REQUIRED_CORPUS_CLASSIFICATION:
        raise ValueError(
            "knowledge-base classification must be synthetic public review"
        )
    for flag in REQUIRED_FALSE_PROVENANCE_FLAGS:
        if value.get(flag) is not False:
            raise ValueError(f"knowledge-base {flag} must be false")
    source = value.get("source")
    if source is not None:
        _require_text(source, "provenance source", max_length=120)
        _reject_private_provenance_source(source)
    for item in value.values():
        if isinstance(item, bool):
            continue
        if isinstance(item, str):
            _reject_unsafe_corpus_text(item)
            _reject_private_path_or_identifier(item)
            continue
        raise ValueError("knowledge-base provenance fields must be text or booleans")
    return {key: value[key] for key in sorted(value)}


def _parse_chunk(
    item: object,
    provenance: dict[str, Any],
    limits: RetrievalConfig,
) -> Chunk:
    if not isinstance(item, dict):
        raise ValueError("knowledge-base chunks must be objects")
    chunk_id = _require_text(item.get("chunk_id"), "chunk_id", max_length=80)
    document_id = _require_text(item.get("document_id"), "document_id", max_length=80)
    text = _require_text(
        item.get("text"),
        "text",
        max_length=limits.max_chunk_text_chars,
    )
    source = _require_text(
        item.get("source"),
        "source",
        max_length=limits.max_source_chars,
    )
    title = _require_text(
        item.get("title"),
        "title",
        max_length=limits.max_title_chars,
    )
    version = _require_text(item.get("version"), "version", max_length=40)
    _reject_private_source_label(source)
    _reject_unsafe_corpus_text(text)
    _reject_unsafe_corpus_text(title)
    _reject_private_path_or_identifier(text)
    _reject_private_path_or_identifier(title)
    chunk_provenance = item.get("provenance")
    if chunk_provenance is None:
        parsed_provenance = dict(provenance)
    else:
        parsed_provenance = _validate_provenance(chunk_provenance)
        _require_matching_provenance(parsed_provenance, provenance)
    return Chunk(
        document_id=document_id,
        chunk_id=chunk_id,
        title=title,
        source=source,
        text=text,
        version=version,
        provenance=parsed_provenance,
    )


def _parse_query(item: object, limits: RetrievalConfig) -> DeclaredQuery:
    if not isinstance(item, dict):
        raise ValueError("declared queries must be objects")
    query_id = _require_text(item.get("id"), "query id", max_length=80)
    query = _require_text(
        item.get("query"),
        "query",
        max_length=limits.max_query_chars,
    )
    expected = _require_text(
        item.get("expected_chunk_id"),
        "expected_chunk_id",
        max_length=80,
    )
    return DeclaredQuery(
        query_id=query_id,
        query=query,
        expected_chunk_id=expected,
    )


def _parse_negative_queries(value: object, limits: RetrievalConfig) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("declared negative queries must be an array")
    queries = tuple(
        _require_text(item, "negative query", max_length=limits.max_query_chars)
        for item in value
    )
    if len(set(queries)) != len(queries):
        raise ValueError("declared negative queries must be unique")
    return queries


def _documents_from_chunks(
    chunks: tuple[Chunk, ...],
    provenance: dict[str, Any],
) -> tuple[Document, ...]:
    documents: dict[str, Document] = {}
    for chunk in chunks:
        if chunk.document_id not in documents:
            documents[chunk.document_id] = Document(
                document_id=chunk.document_id,
                title=chunk.title,
                source=chunk.source,
                version=chunk.version,
                provenance=dict(chunk.provenance or provenance),
            )
    return tuple(documents[key] for key in sorted(documents))


def _require_text(value: object, name: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must not be blank")
    if len(text) > max_length:
        raise ValueError(f"{name} exceeds the trusted length bound")
    return text


def _reject_duplicate_ids(values: list[str], name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {name} values are not allowed")


def _require_matching_provenance(
    chunk_provenance: dict[str, Any],
    corpus_provenance: dict[str, Any],
) -> None:
    if chunk_provenance != corpus_provenance:
        raise ValueError("chunk provenance must match the corpus provenance")


def _reject_private_source_label(source: str) -> None:
    parts = re.split(r"[\\/]+", source)
    if any(part in {".", ".."} for part in parts):
        raise ValueError("knowledge-base source must not contain path traversal")
    if len(parts) != 1 or not _PUBLIC_SOURCE_PATTERN.fullmatch(source):
        raise ValueError("knowledge-base source must be a public filename label")
    if "hometutor" in source.casefold():
        raise ValueError("knowledge-base source must be a public label")


def _reject_unsafe_corpus_text(text: str) -> None:
    if _UNSAFE_CORPUS_PATTERN.search(text):
        raise ValueError("knowledge-base text must not contain secrets or injection")


def _reject_private_provenance_source(source: str) -> None:
    if not _PUBLIC_PROVENANCE_SOURCE_PATTERN.fullmatch(source):
        raise ValueError("knowledge-base provenance source must be a public label")
    _reject_private_path_or_identifier(source)


def _reject_private_path_or_identifier(text: str) -> None:
    lowered = text.casefold()
    if "hometutor" in lowered:
        raise ValueError("knowledge-base text must not contain private paths")
    if _PRIVATE_PATH_PATTERN.search(text) or _EMAIL_PATTERN.search(text):
        raise ValueError(
            "knowledge-base text must not contain private paths or identifiers"
        )
