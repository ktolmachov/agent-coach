# ADR 0002: Diploma Adapter Boundary

Date: 2026-08-23

Status: Accepted for the D8 local-vector boundary

## Context

The diploma review needs literal vector memory and later optional live-provider
function calling. Those features must not rewrite the already reviewed Agent
Core or turn the public demo into a production RAG or LLM platform.

## Decision

Agent Core remains the only orchestration loop and continues to depend on
`ToolExecutionPort`, not on embedding or provider SDKs.

Retrieval-specific ports live in `agent_coach.retrieval`:

- `EmbeddingPort` is implemented first by the deterministic hashed embedder.
  A later provider embedder may replace it without Core changes.
- `VectorStorePort` is implemented first by the bounded in-memory cosine
  store. A later durable store would be a new adapter, not a Core change.

Composition roots choose an explicit adapter profile:

- `mock` remains the offline default;
- `local_vector` uses packaged synthetic notes and real cosine search;
- a later live-provider profile may add an official SDK behind the same
  runner and tool port.

The public `rag.search` schema stays frozen. Threshold, corpus selection and
index construction are trusted composition concerns.

## Non-Goals

- production vector database;
- persisted index artifacts;
- provider SDK in the base install;
- second orchestration framework;
- production MCP, auth or durable run state;
- claiming the hashed embedder is a neural embedding model.

## Consequences

D8 can prove query -> vector -> similarity -> top-k without network. Later
live-provider work can attach to the same ports. Reviewers can keep using the
deterministic mock profile as the regression oracle.
