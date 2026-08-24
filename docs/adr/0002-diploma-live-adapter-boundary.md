# ADR 0002: Diploma Adapter Boundary

Date: 2026-08-23

Status: Accepted for the D8 local-vector boundary and D9 live-provider adapter

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
- `live_provider` uses the official OpenAI Python SDK / Responses API behind
  the same runner and `ToolExecutionPort`. Credentials and SDK imports stay in
  the adapter/composition layer.

The public `rag.search` schema stays frozen. Threshold, corpus selection and
index construction are trusted composition concerns.

## Non-Goals

- production vector database;
- persisted index artifacts;
- provider SDK in the base install;
- second orchestration framework;
- production MCP, auth or durable run state;
- claiming the hashed embedder is a neural embedding model;
- treating a scripted Responses client as a live provider run.

## Consequences

D8 can prove query -> vector -> similarity -> top-k without network. D9 can
prove native function calling and two model roles with a scripted official-SDK
shape, without putting the SDK in the base install. Reviewers can keep using
the deterministic mock profile as the regression oracle.
