# Agent Coach — Agent Contract

This file is the always-on contract for AI coding agents working in this
repository. It applies to the whole tree unless a more specific `AGENTS.md`
exists below the file being changed.

## Purpose and Sources of Truth

Agent Coach is a standalone public diploma demo, not a production HomeTutor
service. It must install, import, test and run in public CI without a private
HomeTutor checkout, private infrastructure or provider credentials.

- Treat executable code and tests as the source of truth for current behavior.
- Use `docs/architecture.md` for layer boundaries and
  `docs/implementation_plan.md` for slice scope, status, promotion criteria and
  rollback guidance.
- Use `README.md` for supported user commands and `CONTRIBUTING.md` for the
  contributor workflow.
- When documentation conflicts with behavior, do not silently choose one:
  preserve safety, determine the intended contract from tests and the current
  slice, then update stale documentation within the authorized write-set.

## Non-Negotiable Boundaries

- `src/agent_coach/core/` stays framework-independent and deterministic. It
  may use the Python standard library and package-owned core modules, but no
  FastAPI, HTTP or provider clients, MCP SDK, SQLite, environment reads or
  filesystem fixture paths.
- `src/agent_coach/mock/` is the default profile. Keep it deterministic,
  offline, read-only and based only on synthetic public fixtures.
- `src/agent_coach/retrieval/` remains an optional offline, in-process local
  vector profile. Do not turn it into a persisted or production vector store.
- `src/agent_coach/provider/` and `src/agent_coach/profiles/` own optional live
  provider integration and routing. Keep SDK imports lazy, provider-specific
  objects out of Core and live behavior opt-in; never add a silent mock
  fallback for provider failures.
- `src/agent_coach/api/` owns HTTP concerns and composition. Preserve the
  localhost-only boundary, request-size enforcement, strict request schemas,
  stable error envelopes and in-memory-only state.
- `contracts/`, `fixtures/` and packaged data contain only versioned,
  deterministic, public-safe artifacts with documented provenance.
- Do not add HomeTutor runtime imports or make any default check depend on a
  sibling checkout. Cross-checking a separately available HomeTutor checkout
  may only be an explicit maintainer action.

## Safety and Data Handling

- Never commit or echo secrets, credentials, tokens, real learner data,
  provider payload dumps, private paths, caches, databases or generated
  runtime state.
- Treat prompts, tool arguments, provider responses, retrieved text and HTTP
  input as untrusted data. Validate at boundaries, enforce size limits and
  fail closed for unknown, ambiguous or malformed tool calls.
- Do not add write-enabled tools, production authentication, durable state,
  non-loopback serving or production network deployment without a separate,
  explicit architecture decision.
- Do not claim or imply production readiness, deployment approval, security
  certification or parity that is not backed by executable evidence.
- Avoid bare `except` and newly introduced broad exception handling. If a
  boundary must catch `Exception`, keep the scope narrow, preserve safe error
  semantics, justify it in code and cover it with a focused test.

## Change Workflow

1. Read `git status` and the relevant diff before editing. Existing changes
   belong to the user; preserve them and avoid unrelated cleanup.
2. Identify the active slice and its write-set in
   `docs/implementation_plan.md`. Work on one slice at a time and do not begin
   the next slice automatically. A user-requested maintenance change outside a
   feature slice must remain limited to its explicitly requested surface.
3. Inspect only the code, tests and documentation needed for the task. Prefer
   `rg`/`rg --files` for discovery and follow existing public interfaces before
   introducing new abstractions.
4. Make the smallest coherent change. Do not perform drive-by refactors, hide
   failures behind compatibility shims or feature flags, or add dependencies
   without a demonstrated need and corresponding metadata/notices.
5. Update tests with behavior changes. Update public documentation when a
   supported command, dependency, contract, architecture boundary or known
   limitation changes.
6. Run targeted checks for the touched surface. Expand to broader checks only
   when the change crosses boundaries, affects a release gate or a reviewer
   explicitly asks for them.
7. End with the current slice's promotion report and stop. Report changed
   files, checks run and their results, plus any remaining risks or checks not
   run; never state that a check passed unless it was actually executed.

## Verification Commands

Use the active virtual environment when available; otherwise use `python`.
Choose the narrowest applicable set:

```text
python -m pytest <relevant test files or -k expression>
python -m ruff check <touched Python paths>
python -m compileall -q <touched package paths>
python scripts/check_contract_export.py      # contract/export changes
python scripts/check_openapi_snapshot.py     # API/OpenAPI changes
python scripts/check_drift_gate.py           # parity/boundary changes
python scripts/check_public_release.py       # release-surface changes
```

Provider, router and live-profile tests must remain deterministic and run
without network access or provider credentials. The full test suite and fresh
install/release checks are reserved for cross-cutting or release validation.

## Slice Ownership

Slices and their current status are defined only in
`docs/implementation_plan.md`; do not duplicate or infer their status here.
Preserve ownership boundaries when working in later slices, especially the
Core/adapters/API separation. No production migration or next-slice work begins
without an explicit approved slice.
