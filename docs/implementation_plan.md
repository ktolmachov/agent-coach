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

Inputs:

- completed D1-D6 artifacts;
- passing CI;
- final public safety review.

Write-set:

- reviewer guide, demo evidence, release notes and final checklist;
- optional tagged release preparation materials;
- documentation updates for exact commands that work from a fresh clone.

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
