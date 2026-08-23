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
