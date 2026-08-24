# Changelog

## 0.1.0 - Unreleased

### Added

- Public repository foundation for the Agent Coach diploma demo.
- Installable Python package skeleton with zero runtime dependencies.
- Public-safe documentation for architecture, provenance, API status, demo
  status and the D1-D7 implementation plan.
- Least-privilege CI workflow and smoke test.
- Exported Agent contract bundle `agent-contracts/1.0.0` with file-level
  provenance manifest.
- Deterministic public contract test vector and offline export verifier.
- Framework-independent Agent Core behind explicit ports.
- Deterministic offline mock adapters, synthetic public fixtures and focused
  adapter/security/golden tests.
- Packaged mock fixture and contract resources for wheel-installed offline
  runs.
- Localhost-only FastAPI Mock Agent API with health, readiness, run polling,
  demo contract/tool endpoints, OpenAPI snapshot and Swagger UI.
- D5 API hardening for actual-body payload limits, loopback-only startup,
  strict request schemas, non-reflected idempotency keys and atomic
  idempotency conflicts.
- Public D7 review kit, release checklist, public release gate and deterministic
  diploma demonstration evidence script.
- Offline local-vector retrieval profile with a hashed embedder, in-memory
  cosine store and packaged synthetic diploma knowledge base.
- Optional live-provider profile using the official OpenAI Python SDK /
  Responses API, native function calling and planner/synthesizer routing.
  The SDK is an extra (`[live]`), not a base dependency.
- D11 final-evidence tooling: strict public release mode, a redacted opt-in
  live eval runner, five pre-registered public live cases and a reusable
  architecture review prompt for the public review kit.

### Fixed

- D8 retrieval now uses an adaptive relevance gate, fail-closed chunk
  provenance and source labels, Bearer credential rejection, and a vector
  index fingerprint that includes embedder width.
- Local-vector search applies the caller threshold to every relevance branch,
  compares provenance mappings exactly, rebuilds the in-memory index
  atomically, and names the knowledge-base chunk-set fingerprint separately
  from the vector index fingerprint.
- Diploma knowledge-base provenance now rejects private paths and identifiers,
  and the lexical gate drops queries with unmatched distinctive tokens below
  the semantic-only bound.
- Independent review promoted D8 on the current working tree. D7 remains HOLD.
