# Diploma Review Kit

Agent Coach is a standalone deterministic diploma demo. This kit gives a
reviewer the shortest path from fresh clone to executable evidence without a
private HomeTutor checkout.

## Five-Minute Quickstart

```bash
python -m pip install -e ".[dev]"
python -m pytest
python scripts/run_diploma_demo.py
python scripts/run_eval_gate.py
```

Expected result: the demo prints JSON evidence with
`adapter_profile: "mock"`, `scenario_id: "grounded_success"`,
`answer_status: "grounded"` and `success: true`. The optional live-provider
profile is not this review path.

## Acceptance Commission Run

Package A of the D11 remediation keeps the published acceptance demo as an
explained D11 artifact. Use the active virtualenv interpreter. On Windows, a
bare `python` launcher can be intercepted by the App Execution Alias.

Windows PowerShell, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\.venv\Scripts\python.exe scripts/run_acceptance_demo.py --full-checks --serve --output ../agent-coach-acceptance-report.json
```

POSIX (separate from the Windows invocation above):

```bash
python3 -m pip install -e ".[dev,build]"
python3 scripts/run_acceptance_demo.py --full-checks --serve --output ../agent-coach-acceptance-report.json
```

The script fails closed on the first unsuccessful check, emits a bounded
PASS/FAIL summary, writes optional evidence only outside the checkout and then
keeps the localhost Mock API available for Swagger review until Ctrl+C. It
covers the built wheel, public gates, deterministic mock and local-vector
profiles, scripted provider-contract validation and a real localhost HTTP run.
The HTTP run prints and records the verified chain `question -> selected tools
-> retrieved public context -> grounded cited answer`; any missing or
inconsistent link fails the acceptance run rather than treating a static API
response as agent evidence.
The same API process also runs a contrast set: learning, due-card and unsafe
retrieval questions must produce three distinct tool routes with one grounded
answer and two safe abstentions. The external report records every question,
route, source count and answer status under `contrastive_routing`.
It then proves repeatability and boundary safety: the same idempotency key
returns the same accepted run, the stable result projection is unchanged,
selected tool arguments match advertised schemas and contain no harness
identity fields, and the report stores per-scenario projection hashes plus a
top-level `evidence_payload_sha256`. Negative localhost HTTP checks cover
idempotency conflict, malformed schema, oversized payload, unknown tool,
forbidden identity arguments and unknown run; each must fail closed through the
public error envelope.
It does not call a live provider, create release evidence, authorize production
deployment or create a release tag.

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
committed as release evidence. D11 evidence has three distinct layers:
`docs/evidence/live-eval-public.json` is the committed redacted live public
artifact and does not need to contain `commit` or `worktree_dirty`; the
external live evidence wrapper binds the reviewed immutable commit to that
public artifact's SHA-256 digest; clean-release evidence records
`worktree_dirty: false` plus PASS/exit-code-0 command evidence.
`scripts/check_public_release.py` fails closed when required release evidence is
missing or invalid.

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

The gate freezes the exact registered 27-case public synthetic suite and KPI
thresholds before any live evidence is supplied. It validates suite version,
public provenance, frozen id order and canonical hash, and it also checks the
generated Tool SOP snapshot in `docs/tool_sop.md`.
Promotion remains fail-closed unless Git HEAD is available, live evidence
identifies the current commit, live-provider opt-in, registered evidence
provenance, registered live cases and tracked public artifact labels with
matching SHA-256 digests. The registered case contract includes question,
security assertions and success rule in addition to tools, sources and citation
requirements. The referenced public artifact must declare
`mode: "live_provider"`, `contains_scripted_responses: false`, complete
per-case projections for successful and failed provider cases and a recomputed
task-success rate. Clean release evidence records registered provenance plus
PASS/exit-code-0 fresh-clone, strict
public-release and offline-eval commands with `stdout_sha256`. Oversized,
marker-only or string-only suite/evidence JSON is rejected. Live scores below
80% block promotion without changing offline `gate_status`; promotion evidence
args or `--require-promotion` make `promotion_status` drive the CLI exit code.
The live score is forced-grounding evidence for provider wiring, grounded
synthesis and citations. It is not autonomous planner tool-selection accuracy;
that requires the separate autonomous D11 harness and later opt-in live
artifact.

After the reviewed commit has a valid external live wrapper and external
clean-release evidence, run the full promotion gate:

```bash
python scripts/run_eval_gate.py --live-evidence ../agent-coach-live-wrapper.json --clean-release-evidence ../agent-coach-clean-release-evidence.json --require-promotion --output ../agent-coach-d11-promotion-report.json
```

Without real evidence, `promotion_status: HOLD` is the expected safe result.

Run the full public check sequence:

```bash
python -m pytest
python -m ruff check .
python -m compileall src scripts
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

Strict final release mode adds clean-tree and D11 artifact requirements:

```bash
python scripts/check_public_release.py --release
```

The strict mode is expected to fail until the reviewed commit is clean and
`docs/evidence/live-eval-public.json` exists as redacted opt-in live-provider
evidence. Scripted Responses validation is useful for testing the runner, but
it is not live evidence and is rejected as a release artifact. Empty or
incomplete result objects are also rejected; the gate recomputes the live task
success rate from registered per-case results.

## Live Provider Evidence

The live eval cases are fixed before any provider call. They cover five public
synthetic knowledge-base questions: photosynthesis, spaced repetition,
retrieval practice, active recall flashcards and cognitive load. Each case
expects `rag.search`, forbids tools outside the live read-only subset, requires
a grounded answer with citation to the allowed packaged source and requires
zero security failures or hidden writes.

Offline runner validation:

```bash
python scripts/run_live_eval.py --scripted
```

Opt-in live collection, after explicit approval for network, credentials,
models and possible cost:

```bash
python scripts/run_live_eval.py --allow-network --provider-opt-in --output docs/evidence/live-eval-public.json
```

After the reviewed commit exists, write the external wrapper that binds the
public artifact hash to that immutable commit:

```bash
python scripts/run_live_eval.py --wrapper-only --public-artifact docs/evidence/live-eval-public.json --wrapper-output ../agent-coach-live-wrapper.json
```

The public artifact contains only bounded projections: case contract, executed
tool names, source labels, phase statuses, model roles, token/time summaries
and unknown-cost status. It does not store raw prompts, raw provider payloads,
chain-of-thought, credentials or learner data.

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
