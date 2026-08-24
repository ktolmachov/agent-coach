# Framework-Independent Agent Core

The D3 Agent Core is the standalone orchestration layer for the diploma
distribution. It is deliberately small and has no dependency on FastAPI, HTTP
clients, MCP SDKs, SQLite, provider clients, environment variables or the
private HomeTutor `app.*` package.

Core modules:

- `agent_coach.core.contracts` defines public dataclasses, enums and helpers
  matching the exported D2 contract semantics.
- `agent_coach.core.ports` defines the explicit boundaries for planner,
  message building, security, tool execution, usage accounting, clock and run
  storage.
- `agent_coach.core.runner` owns the framework-independent agent loop.
- `agent_coach.core.stop_controller` owns pure budget and stop decisions.
- `agent_coach.core.security` owns fail-closed argument validation, redaction
  and final-answer guardrails.
- `agent_coach.core.text` owns deterministic source identity and merge helpers.

Provenance:

- The enum and answer-status semantics are distilled from HomeTutor
  `app.agent.contracts` at source commit
  `292be74f97b18615388838c2a1ddf2e0879585e0`.
- Stop-controller semantics are distilled from HomeTutor
  `app.agent.stop_controller` at the same source commit.
- Tool names, counts and harness-only fields are checked against the exported
  D2 vectors under `contracts/agent_contracts/v1/`.

D3 remediation invariants:

- `RunRequest.run_id` must be supplied by the composition root; the core does
  not generate IDs internally, so repeated runs with the same fake ports and
  input remain deterministic.
- External ports are bounded. Planner, message builder, security, tool
  execution, usage accounting and run-store failures return terminal
  `AgentRunResult` values instead of escaping tracebacks.
- Public run steps and run-store events contain redacted compact projections:
  no planner raw payloads, raw retrieved chunks, provider responses or
  credentials are retained.
- Planner-supplied tool arguments fail closed against the supported D2 JSON
  schema subset and the full `forbidden_model_arg_fields` vector, including
  `scopes`.
- Contract bundle loading checks exact `agent-contracts/1.0.0` identity and
  schema hash before building core `ToolSpec` objects.
- Evidence metadata is derived only by core projection code from
  post-sanitized safe evidence. Tool-supplied `has_evidence` is reserved;
  injection-only, secret-only, email-only, bearer-only and private-path-only
  content cannot force a grounded answer, while factual text remains evidence
  after credential/path spans are removed.
- Clock and fallback-answer failures are bounded; the package default fallback
  is used when a security policy fallback fails or returns malformed data.
- Tool-result summaries, final answers, mapping keys, tool names, source labels
  and nested metadata are screened for prompt-injection markers, secrets and
  private or absolute Windows, POSIX, file-URI and UNC paths before they reach
  planner context, result projections or run-store events. HTTP(S) URLs remain
  byte-for-byte public labels, including path, query and fragment components.
- Terminal tool-call paths record the step before the completed event.

The core is not a runnable API server and does not own deterministic mock
adapters internally. D4 mock adapters live in `agent_coach.mock` and use the
core only through explicit ports. Core tests still use in-test fake ports to
characterize the port contract without coupling core behavior to fixtures.

D9 adds a typed `PlannerCallResult` so live adapters can return routing
metadata (`step_id`, `model_role`, `model_id`, `backend`, `routing_status`)
without hiding it in `thought`, `raw` or token maps. Deterministic mock and
local-vector planners return an empty routing tuple.

D10 adds a stable `trace["phases"]` projection derived from the same
`AgentRunner` steps. It always appears in this order:

1. `scenario_selection`;
2. `learner_context`;
3. `knowledge_retrieval`;
4. `practice_branch`;
5. `final_validation`.

Each phase contains only safe bounded fields: `status`, `detail`,
deterministic step-based start, `duration_ms`, `step_ids`, `tool_call_ids`,
`tool_names`, model roles/provider call ids when present, usage and cost
summaries. The retrieval phase contains counts and grounding booleans, not raw
chunks. A retrieval phase is completed only when a retrieval tool produced
usable grounding evidence; weak retrieval is marked failed and final answers
without retrieval citations abstain by the existing answer-status contract.
`scenario_selection` is completed only for explicit scenario-backed requests
with a safe `scenario_id`; local-vector, live-provider and direct Core requests
without a scenario selector mark it skipped. Local non-provider runs report
`cost_status: "local_zero"` with `total_cost_usd: 0.0`; unpriced
live-provider requests and cloud-backed phase routes report
`cost_status: "unknown"` and never project a false zero, even when a local tool
reports a partial estimated cost. Skipped phases without usage or routes keep a
phase-local `local_zero` cost summary.
