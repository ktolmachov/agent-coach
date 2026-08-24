# Implementation Plan

This plan is self-contained for the public Agent Coach diploma demo. Work one
slice at a time. Each slice ends with checks and a promotion report. The next
slice does not start automatically.

Any production network boundary, durable service deployment, production
authentication or ownership cutover requires a separate future architecture
decision.

## Global Rules

- Keep the repository installable without a private checkout.
- Do not add secrets, learner data, provider credentials, caches, database
  files or generated runtime state.
- Do not describe the demo as production capable.
- Do not add HomeTutor imports.
- Keep deterministic offline defaults until a future production decision
  explicitly replaces mock adapters.
- Use targeted tests and static checks for the touched slice.
- Stop after the promotion report.

## D1 - Public Repository Foundation

Status: complete.

Inputs:

- public boundary decision derived from source architecture evidence;
- existing Apache-2.0 license;
- empty public repository baseline.

Write-set:

- package metadata, CI, public documentation, package skeleton and smoke tests;
- placeholder README files for future contracts, fixtures and scripts.

Non-goals:

- no Agent Core;
- no contracts or fixtures;
- no Mock Agent API;
- no runtime dependencies.

Promotion thresholds:

- package installs and imports from outside the checkout;
- runtime dependencies remain empty;
- public docs are safe to publish;
- CI is least privilege.

Checks:

- fresh virtual environment install/import;
- Pytest, Ruff and compileall;
- metadata inspection;
- secret, path, HomeTutor-import and production-claim scans.

Rollback:

- return the repository to the license-only baseline or revert the D1 commit.

Stop:

- stop after the D1 promotion report.

## D2 - Contract and Provenance Export

Status: complete.

Inputs:

- accepted D1 foundation commit;
- public-safe source contract evidence selected for export;
- exact source commit recorded in provenance;
- D1 provenance and boundary ADR.

Write-set:

- `contracts/` versioned public contract files;
- deterministic public test vectors if needed to validate the contracts;
- file-level export manifest with source path, target path, source hash,
  target hash and transformation;
- contract validation tests and any small verification script owned by D2;
- documentation updates that describe only exported D2 artifacts.

Non-goals:

- no Agent Core implementation;
- no adapters, fixtures for runtime replay or Mock Agent API;
- no production auth, production data or private paths;
- no manual two-way synchronization with any private repository.

Promotion thresholds:

- schema parity is 100% for exported public contracts;
- exported contracts are deterministic and byte-stable for the same source;
- repeated export from the same source is byte-identical;
- manifest covers every exported file;
- public CI can validate the contracts without a private checkout;
- no HomeTutor runtime imports or hidden local dependency.

Checks:

- contract schema validation;
- manifest hash verification;
- repeated export or verification is deterministic;
- Pytest and Ruff for D2-owned code;
- secret, private-path and prohibited-claim scans.

Rollback:

- remove D2 contract artifacts, tests, scripts and docs or revert the D2
  commit; D1 foundation remains intact.

Stop:

- stop after the D2 promotion report. Do not start D3.

## D3 - Framework-Independent Agent Core

Status: complete.

Inputs:

- D2 contracts and public test vectors;
- documented behavior expectations for the minimal Agent Core;
- D1 import boundary rules.

Write-set:

- `src/agent_coach/core/` modules for public contracts, ports, runner, stop
  control, security and text helpers;
- focused unit tests and characterization tests for core behavior;
- docs explaining the core boundary.

Non-goals:

- no FastAPI or other web framework;
- no HTTP clients, MCP SDK, provider clients or SQLite;
- no filesystem fixture loading from core modules;
- no environment reads;
- no production adapter implementation.

Implemented artifacts:

- `src/agent_coach/core/contracts.py`;
- `src/agent_coach/core/ports.py`;
- `src/agent_coach/core/runner.py`;
- `src/agent_coach/core/stop_controller.py`;
- `src/agent_coach/core/security.py`;
- `src/agent_coach/core/text.py`;
- `tests/test_core.py`;
- `docs/core.md`.

Promotion thresholds:

- core imports only standard-library and package-owned modules allowed by the
  boundary;
- deterministic fake ports can complete a minimal run;
- stop and security behavior is covered by tests;
- public behavior matches D2 contract expectations.

Checks:

- Pytest for core tests;
- Ruff and compileall;
- import-boundary scan for forbidden dependencies;
- secret and production-claim scans.

Rollback:

- remove D3 core modules, tests and docs or revert the D3 commit; D1-D2 remain
  intact.

Stop:

- stop after the D3 promotion report. Do not start D4.

## D4 - Deterministic Mock Adapters

Status: complete.

Inputs:

- D3 Agent Core ports;
- D2 contracts;
- planned synthetic scenarios for offline review.

Write-set:

- deterministic planner, tool adapter, security policy, clock and ephemeral
  run store;
- synthetic fixtures with explicit public provenance;
- adapter tests and golden assertions;
- docs for deterministic offline behavior.

Implemented artifacts:

- `src/agent_coach/mock/fixtures.py`;
- `src/agent_coach/mock/adapters.py`;
- `src/agent_coach/mock/composition.py`;
- `src/agent_coach/data/mock_scenarios.json`;
- `src/agent_coach/data/agent_contract_bundle.json`;
- `fixtures/mock_scenarios.json`;
- `tests/test_mock_adapters.py`;
- `docs/mock_adapters.md`.

D4 remediation evidence:

- ephemeral store projections sanitize request `run_id`, `user_id`, `question`
  and completed trace fields before retention;
- default fixture and contract loading uses package resources, so wheel installs
  do not require a source checkout;
- focused adapter tests include package-resource parity, tainted-store
  regression coverage, exact stable scenario projections and all controlled
  outcome categories.

Non-goals:

- no network access;
- no write-enabled tools;
- no production credentials, learner data or durable state;
- no API server.

Promotion thresholds:

- advertised mock tool schemas are covered at 100%;
- semantic parity with exported golden assertions is at least 95%;
- security assertions pass at 100%;
- repeated runs are deterministic;
- advertised mock tools are fully covered by tests;
- security fixtures for injection, fake secrets and oversized outputs pass;
- no writes outside explicitly temporary test locations.

Checks:

- Pytest for adapter and golden tests;
- Ruff and compileall;
- no-network and no-write assertions where practical;
- secret, path and production-claim scans.

Rollback:

- remove D4 adapters, fixtures, tests and docs or revert the D4 commit;
  contracts and core remain intact.

Stop:

- stop after the D4 promotion report. Do not start D5.

## D5 - Local Mock Agent API

Status: complete.

Inputs:

- D4 deterministic composition;
- D2 contracts;
- documented local API shape.

Write-set:

- local API layer and composition root;
- request and response schemas;
- API tests, OpenAPI snapshot and local run documentation;
- startup defaults that bind only to localhost.

Implemented artifacts:

- `src/agent_coach/api/`;
- `tests/test_api.py`;
- `docs/openapi.json`;
- `scripts/check_openapi_snapshot.py`;
- local API documentation in `README.md`, `docs/api.md` and `docs/demo.md`.

D5 HOLD remediation evidence:

- request-size limits are enforced on the actual ASGI receive stream, including
  chunked requests without `Content-Length`;
- startup accepts only `localhost` or loopback IP addresses;
- request models reject top-level extra fields and publish
  `additionalProperties: false` in OpenAPI;
- raw `Idempotency-Key` values are not reflected to clients;
- idempotency check/commit is atomic for conflicting concurrent requests;
- documented validation errors use the common `ErrorResponse` envelope.

Non-goals:

- no production authentication;
- no durable production run store;
- no production network deployment;
- no write-enabled HITL receipts while the mock profile is read-only;
- no cancellation route until it is implemented and tested.

Promotion thresholds:

- API contract assertions pass at 100%;
- security assertions pass at 100%;
- API returns the documented run lifecycle using `state`, not `status`;
- OpenAPI contains only implemented routes;
- idempotency, validation and error envelope behavior are tested;
- stack traces and secrets are not returned to clients.

Checks:

- API test suite;
- OpenAPI snapshot validation;
- Pytest, Ruff and compileall;
- localhost default inspection;
- secret, path and production-claim scans.

Rollback:

- remove D5 API modules, tests, OpenAPI artifacts and docs or revert the D5
  commit; D1-D4 remain intact.

Stop:

- stop after the D5 promotion report. Do not start D6.

## D6 - Parity and Drift Gate

Inputs:

- D2 manifest and exported contracts;
- D3-D5 executable behavior;
- current source evidence hash recorded for comparison.

Write-set:

- drift-check command or script;
- parity tests and documentation;
- CI updates that run the public drift checks without private checkout access.

Implemented artifacts:

- `scripts/check_drift_gate.py`;
- `tests/test_drift_gate.py`;
- `docs/drift_gate.md`;
- CI steps for contract export, OpenAPI snapshot and public drift gate.

D6 HOLD remediation evidence:

- semantic parity is scenario-level exact projection-hash parity, including
  answer, sources, trace, steps and tool outcomes, using a frozen independent
  hash snapshot rather than production sanitizer/helper code;
- fixture and frozen golden scenario id sets must match exactly, and golden
  hashes must be lowercase sha256 digests;
- runtime absolute-path scanning covers common private path forms in code and
  runtime-consumed resources;
- Python scanning folds bounded constant string concatenations so split path
  literals cannot bypass the gate;
- negative tests exercise the D6 gate directly for semantic corruption,
  shared-helper drift, path bypasses, bounded CLI failure, malformed bundles
  and current source contract drift.

Non-goals:

- no new runtime features;
- no contract redesign;
- no production migration or ownership cutover.

Promotion thresholds:

- contract hashes equal the D2 manifest values;
- semantic parity with exported golden assertions is at least 95%;
- security assertions pass at 100%;
- public checks detect manifest tampering and contract drift;
- CI fails on drift;
- parity claims are backed by executable checks, not static inspection alone.

Checks:

- manifest verification;
- parity and drift tests;
- Pytest, Ruff and compileall;
- secret, path and production-claim scans.

Rollback:

- remove D6 drift tools, tests, CI changes and docs or revert the D6 commit.

Stop:

- stop after the D6 promotion report. Do not start D7.

## D7 - Diploma Review Kit and Release

Status: HOLD pending independent promotion review.

Inputs:

- completed D1-D6 artifacts;
- passing CI;
- final public safety review.

Write-set:

- reviewer guide, demo evidence, release notes and final checklist;
- optional tagged release preparation materials;
- documentation updates for exact commands that work from a fresh clone.

Implemented artifacts:

- `docs/review_kit.md`;
- `docs/release_checklist.md`;
- `docs/dependency_notices.md`;
- `scripts/run_diploma_demo.py`;
- `scripts/check_public_release.py`;
- `tests/test_diploma_demo.py`;
- `tests/test_public_release_gate.py`;
- D7 documentation updates in `README.md`, `docs/demo.md`,
  `scripts/README.md`, `SECURITY.md` and `CHANGELOG.md`.

D7 release evidence:

- `scripts/run_diploma_demo.py` emits deterministic JSON evidence with commit,
  dirty-worktree flag, mock profile, contract hash, advertised tools, terminal
  result projection and limitations;
- `scripts/check_public_release.py` validates required review files, README
  safety wording, concrete private security reporting fallback, private local
  path markers and high-confidence secret patterns in all text-decodable
  release files including tests and unknown suffixes, current OpenAPI,
  internal Markdown links, release evidence freshness, sensitive credential
  containers and tracked or dirty generated release artifacts;
- release tag creation remains gated on explicit maintainer approval.

HOLD remediation status:

- public release gate now fails closed for generic private paths, secret-like
  credentials, PEM private keys, GitHub/OpenAI token forms, production-readiness
  claims outside README, missing concrete private security fallback, sensitive
  credential containers and stale/dirty release evidence;
- promotion remains pending an independent D7 review on a clean commit.

Non-goals:

- no production service claims;
- no production auth or durable production state;
- no future ADR-0008 work;
- no hidden dependency on private infrastructure.

Promotion thresholds:

- full public release gate passes before publishing;
- fresh clone install, tests and demo commands pass;
- docs links resolve;
- secret and private-path scans are clean;
- GitHub Private Vulnerability Reporting is enabled or a concrete private
  security contact is documented;
- release evidence is reproducible by a reviewer.

Checks:

- full public test suite;
- Ruff and compileall;
- docs link checks;
- secret, path and dependency review;
- fresh clone or disposable-directory smoke.

Rollback:

- remove D7 release materials or revert the D7 commit; keep prior accepted
  slices intact.

Stop:

- stop after the D7 promotion report. Do not start any production migration.

## D8 - Real Local Vector Memory and Retrieval

Status: complete.

Inputs:

- implemented D1-D7 artifacts; D7 remains HOLD pending independent
  promotion review, so D8 does not treat D7 as accepted;
- frozen public `rag.search` schema;
- framework-independent Agent Core ports.

Write-set:

- retrieval contracts and ports outside Core;
- packaged synthetic diploma knowledge base;
- deterministic hashed embedder and in-memory cosine store;
- `rag.search` tool adapter and local-vector composition;
- focused retrieval tests and adapter-boundary documentation.

Implemented artifacts:

- `src/agent_coach/retrieval/`;
- `src/agent_coach/data/diploma_knowledge_base.json`;
- `tests/test_retrieval.py`;
- `docs/retrieval.md`;
- `docs/adr/0002-diploma-live-adapter-boundary.md`.

Independent promotion review:

- verdict `PROMOTE D8` on the current working tree;
- private path, email and HomeTutor path in `provenance.source` fail closed;
- declared homonym negatives return empty retrieval;
- caller `threshold=1.0` returns no weaker hits;
- a failed NaN build leaves store size and both fingerprints unchanged;
- `chunk_set_fingerprint` and `index_fingerprint` remain distinct identities;
- residual hashed-lexical ambiguity is documented as a D8 limitation, not as
  neural semantic retrieval.

Non-goals:

- no Core rewrite;
- no public API or OpenAPI change;
- no provider SDK or live profile;
- no persisted index, production vector database or HomeTutor data.

Promotion thresholds:

- retrieval unit and contract tests pass;
- declared query set top-1 is 100%;
- security assertions pass;
- deterministic repeat is 100%;
- network calls, model downloads and filesystem writes stay at 0;
- default mock profile does not regress.

Checks:

- targeted retrieval tests;
- one mock-profile regression;
- Ruff and compileall on the touched surface;
- import-boundary scan of retrieval and core modules.

Rollback:

- remove the retrieval package, packaged corpus, retrieval tests and D8 docs
  or revert the D8 commit; keep D1-D7 intact.

Stop:

- stop after the D8 promotion report. Do not start D9.

## D9 - Provider-Native Function Calling and Model Routing

Status: COMPLETE locally; HOLD pending independent promotion review.

Inputs:

- promoted D8 local-vector retrieval;
- D7 remains HOLD and is not a D9 blocker;
- framework-independent Agent Core ports;
- frozen public tool schemas.

Write-set:

- optional `[live]` extra for the official OpenAI Python SDK;
- provider config, model router, tool-schema conversion and Responses adapter;
- live-provider composition root;
- focused offline tests with a scripted Responses client;
- adapter-boundary documentation.

Implemented artifacts:

- `src/agent_coach/provider/`;
- `src/agent_coach/profiles/live.py`;
- `tests/test_model_router.py`;
- `tests/test_openai_responses_adapter.py`;
- `tests/test_live_profile_contract.py`;
- `docs/live_profile.md`.

Core contract evolution:

- `PlannerPort.decide` now returns `PlannerCallResult` so routing metadata is
  not stored in `thought`, `raw` or token maps;
- mock and local-vector planners remain scripted and are unchanged in default
  behavior;
- `model_routes` is added to a run trace only when routing metadata exists, so
  mock golden projections stay stable.

D9 completion evidence:

- the optional live dependency requires OpenAI Python SDK 1.66 or newer, and
  composition rejects installed clients without callable `responses.create`;
- stateless Responses requests include `reasoning.encrypted_content`;
- replay preserves valid provider `response.output` and fails closed for
  oversized, malformed or mismatched replay-critical items;
- provider response status must be explicit `completed`, and unsafe status
  values stay out of bounded errors;
- provider API base validation rejects encoded and double-encoded secret-like
  paths before public projection;
- token usage accounting uses at least `prompt_tokens + completion_tokens`
  even when provider `total_tokens` is lower;
- no-tool planner responses return to Agent Core before any synthesizer call,
  so hard token and time limits are rechecked between provider calls;
- provider output text is bounded locally when the provider ignores
  `max_output_tokens`;
- replay diagnostics use static field labels and do not expose
  provider-controlled mapping keys;
- remote HTTP API bases are rejected unless the host is loopback for a local
  emulator;
- malformed provider and Core port usage counters fail closed instead of being
  coerced to zero;
- unsupported provider `response.output` item types fail closed before tool
  execution;
- supported provider `response.output` item types are validated against their
  replay-critical schemas before tool execution;
- completed planner and synthesizer responses validate saved output items
  before accepting either a tool call or final answer;
- raw, SDK-object and direct normalized replay items share bounded projection
  limits for per-field text, cumulative text, node count, depth and cycles;
- nested replay mapping keys must be strings and count toward the same node and
  cumulative-text limits, so key coercion cannot bypass replay bounds;
- replay `function_call` items must exactly match normalized function calls by
  `call_id`, `name` and `arguments`, with no extras or duplicates;
- no-tool planner responses are documented and tested as terminal planner
  answers or abstentions, not synthesizer evidence;
- stateless replay preserves valid assistant message item `phase` values
  unchanged and rejects malformed, misplaced or non-assistant message phase
  values;
- secret-like API base hostnames are rejected before public projection.

Non-goals:

- no second orchestration loop;
- no public API/OpenAPI change;
- no production auth, MCP, write tools or durable provider state;
- no committed API keys or raw provider dumps;
- no D10 phase-trace work.

Promotion thresholds:

- provider wire/contract tests pass without network;
- planner and synthesizer routes use distinct configured model ids;
- invalid/unknown/multiple native calls fail closed;
- silent mock fallback is 0;
- secret exposure is 0;
- default mock profile does not regress.

Checks:

- targeted provider, router and live-profile tests;
- one mock-profile regression;
- Ruff and compileall on the touched surface;
- import-boundary scan of core and lazy SDK import.

Rollback:

- remove the provider/profile packages, live tests and D9 docs or revert the
  D9 commit; keep D1-D8 intact.

Stop:

- stop after the D9 promotion report. Do not start D10.
