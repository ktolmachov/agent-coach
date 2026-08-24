# Diploma Review Kit

Agent Coach is a standalone deterministic diploma demo. This kit gives a
reviewer the shortest path from fresh clone to executable evidence without a
private HomeTutor checkout.

## Five-Minute Quickstart

```bash
python -m pip install -e ".[dev]"
python -m pytest
python scripts/run_diploma_demo.py
```

Expected result: the demo prints JSON evidence with
`adapter_profile: "mock"`, `scenario_id: "grounded_success"`,
`answer_status: "grounded"` and `success: true`. The optional live-provider
profile is not this review path.

## Architecture

```text
reviewer
  -> README, review kit, Swagger UI, curl
  -> localhost-only Mock Agent API
  -> API composition root
  -> framework-independent Agent Core
  -> deterministic mock adapters
  -> synthetic public fixtures and exported public contracts
```

The local API is a review surface over deterministic mock adapters. It is not a
production service, has no production authentication, uses no production data
and stores runs only in process memory.

## Demo Scenarios

The synthetic scenarios live in `fixtures/mock_scenarios.json` and are also
packaged as importable resources. They cover:

- grounded success;
- empty retrieval or practice context;
- validation failure;
- timeout, rate limit and dependency failure;
- security failure;
- oversized result compaction;
- prompt injection and fake secret redaction;
- forbidden harness identity arguments.

Run a specific scenario:

```bash
python scripts/run_diploma_demo.py --scenario prompt_injection
```

## Literal Review Example

Input:

```text
Explain photosynthesis and suggest practice.
```

Reason -> Act -> Observe -> result:

```text
Reason: load the synthetic learner context.
Act: learner.get_profile({})
Observe: public demo preferences only.
Reason: retrieve grounded source evidence.
Act: rag.search({"query": "photosynthesis energy glucose", "top_k": 2})
Observe: photosynthesis-basics.md with cite index [1].
Reason: create a bounded practice branch.
Act: quiz.generate({"topic": "photosynthesis", "learning_mode": "practice"})
Observe: two synthetic practice questions.
Result: Photosynthesis converts light energy into chemical energy stored in
glucose [1]. Practice next with two retrieval questions.
```

The public trace includes sources, five stable phases, tool names, token/time
metrics and cost status. Mock and local-vector profiles report `local_zero`
cost. Live-provider traces report unknown cloud cost unless a future reviewed
pricing table exists.

Write reproducible JSON evidence:

```bash
python scripts/run_diploma_demo.py --output ../agent-coach-diploma-demo.json
```

Keep generated evidence outside the checkout unless it is intentionally
committed as release evidence. Any committed `docs/evidence/*.json` file must
point to the reviewed immutable commit and declare `worktree_dirty: false`;
`scripts/check_public_release.py` fails closed otherwise.

## API Examples

Start the localhost Mock Agent API:

```bash
agent-coach-api
```

Open Swagger UI:

```text
http://127.0.0.1:8008/docs
```

Create and fetch a run:

```bash
curl -s -X POST http://127.0.0.1:8008/v1/runs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-grounded" \
  -d "{\"scenario_id\":\"grounded_success\"}"
```

List the advertised read-only mock tools:

```bash
curl -s http://127.0.0.1:8008/v1/demo/tools
```

The committed OpenAPI artifact is `docs/openapi.json`; verify it with:

```bash
python scripts/check_openapi_snapshot.py
```

## Mock vs Production

| Concern | Mock | Local vector | Optional live provider |
| --- | --- | --- |
| Data | Synthetic public fixtures | Packaged synthetic public corpus | Same local corpus plus provider text |
| Auth | None, localhost-only review | None | API key supplied outside Git/chat/evidence |
| State | Ephemeral in-memory store | In-process vector index | Stateless Responses requests |
| Tools | Read-only deterministic subset | `rag.search` | `rag.search`, `learner.get_profile` |
| Models | Scripted planner | Scripted local planner | Planner and synthesizer roles |
| Evidence | Deterministic | Deterministic | Opt-in and non-deterministic |

Future production work requires a separate architecture decision before any
network, durable-state, authentication or ownership cutover work begins.

Native function calling is demonstrated by the optional live-provider adapter:
frozen `ToolSpec` schemas are converted to Responses function tools, one
provider-native function call is accepted at a time, malformed or unknown calls
fail closed, and raw provider payloads are not stored in public traces.

## Source Provenance

- Boundary ADR: `docs/adr/0001-diploma-distribution-boundary.md`.
- Contract bundle: `contracts/agent_contracts/v1/agent_contract_bundle.json`.
- Export manifest: `contracts/export_manifest.json`.
- Provenance summary: `docs/provenance.md`.
- Drift gate: `python scripts/check_drift_gate.py`.
- Dependency notices: `docs/dependency_notices.md`.

The optional cross-repository drift check is maintainer-only:

```bash
python scripts/check_drift_gate.py --source-root ../hometutor --json
```

Public CI does not require that checkout.

## Test and Eval Evidence

Run the public release gate:

```bash
python scripts/check_public_release.py
```

Run the D11 eval gate:

```bash
python scripts/run_eval_gate.py
```

The gate freezes 27 public synthetic cases and KPI thresholds before any live
evidence is supplied. It also checks the generated Tool SOP snapshot in
`docs/tool_sop.md`.
Promotion remains fail-closed unless live evidence identifies the current
commit, live-provider opt-in, at least five live cases and public artifact
labels, and clean release evidence records PASS/exit-code-0 fresh-clone,
public-release and offline-eval commands.

Run the full public check sequence:

```bash
python -m pytest
python -m ruff check .
python -m compileall src
python scripts/check_contract_export.py
python scripts/check_openapi_snapshot.py
python scripts/check_drift_gate.py
python scripts/check_public_release.py
python scripts/run_eval_gate.py
```

The release gate checks the publishable/runtime surface, including tests, for
private local path markers, high-confidence secret patterns, production
readiness claims, current OpenAPI, required review documents, concrete private
security reporting fallback, internal Markdown links, release evidence
freshness and tracked cache/database artifacts. Synthetic sanitizer fixtures
are allowed only through narrow test-file allowlists.

## Troubleshooting

- If `agent_coach` cannot be imported, rerun
  `python -m pip install -e ".[dev]"` from the repository root.
- If Swagger UI is unavailable, confirm `agent-coach-api` is running and bound
  to `127.0.0.1`.
- If OpenAPI validation fails, run `python scripts/check_openapi_snapshot.py`;
  use `--write` only after an intentional API change.
- If drift validation fails in public mode, inspect
  `fixtures/drift_golden_projection_hashes.json` and the exported contract
  bundle before changing code.
- If optional `--source-root` validation fails, confirm the source checkout path
  is correct and that the source contract changes are intentional.

## Release

Use `docs/release_checklist.md` for the final public release gate. A release tag
must be created only after explicit maintainer approval.
