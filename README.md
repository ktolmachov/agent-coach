# Agent Coach

Agent Coach is a standalone deterministic diploma demo. It demonstrates an
agent layer over retrieval-augmented generation for personalized study
explanations and practice selection: a learner question enters the agent, the
agent reasons about the next step, calls only declared read-only tools, observes
bounded tool results and returns a grounded or abstained result.

The repository is public-safe by design. It has no production authentication,
no production data, no durable production state and no production deployment
approval. The default path is fully offline and deterministic.

## Scenario

```text
input -> Reason -> Act -> Observe -> result
```

For the canonical offline review case:

```text
Input request:
Explain photosynthesis and suggest practice.

Executed tools:
learner.get_profile({})
rag.search({"query": "photosynthesis energy glucose", "top_k": 2})
quiz.generate({"topic": "photosynthesis", "learning_mode": "practice"})

Sources:
photosynthesis-basics.md [1]

Phase statuses:
scenario_selection: completed
learner_context: completed
knowledge_retrieval: completed
practice_branch: completed
final_validation: completed

Safe answer:
Photosynthesis converts light energy into chemical energy stored in glucose
[1]. Practice next with two retrieval questions.

Model roles:
mock/local-vector: scripted local planner
live-provider: planner then synthesizer when a tool observation is available

Tokens/time/cost:
offline profiles report local_zero cost; live-provider reports cloud pricing
as unknown unless a reviewed pricing table exists.
```

## Architecture

```text
mock / local-vector / live-provider
        |
        v
AgentRunner
        |
        v
ports: PlannerPort, ToolExecutionPort, SecurityPolicyPort, RunStorePort
        |
        v
read-only tools: learner.get_profile, rag.search, quiz.generate,
cards.get_due, catalog.list
```

Agent Core lives under `src/agent_coach/core/` and remains framework
independent. The mock profile is the default deterministic profile.
Local-vector retrieval is an optional in-process profile. The live-provider
profile is explicit opt-in and uses the same runner and ports.

## Model Routing

The live-provider adapter has two configured roles:

- `planner`: decides whether one declared native function call is needed.
- `synthesizer`: writes the final grounded answer after a successful tool
  observation.

Routing is based on observed run state, not model-name substrings. The default
model ids are `gpt-4.1-mini` for the planner and `gpt-4.1` for the
synthesizer. If both roles use the same configured model id, the trace records
`degraded_same_model`.

## Native Function Calling

Frozen `ToolSpec` declarations are converted to OpenAI Responses
`type=function` tools. The provider may return one function call; Agent Coach
validates the call id, tool name and JSON arguments, executes the local
read-only tool, sends a matching `function_call_output` on the next stateless
turn and normalizes the result into a `PlannerDecision`. Unknown tools,
multiple tool calls, malformed arguments, unsupported response items and raw
provider payload leakage fail closed.

## Vector Memory

The local-vector profile builds deterministic hashed n-gram vectors from the
packaged synthetic knowledge base, compares them with cosine similarity and
returns top-k source chunks through `rag.search`. This proves the vector-memory
path without network access, but it is not a neural embedding model and not a
production vector database.

## Install

```bash
python -m pip install -e .
python -c "import agent_coach; print(agent_coach.__version__)"
```

Use the active virtual environment if `python` is not on PATH:

```bash
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Offline Quickstart

```bash
python -m pip install -e ".[dev]"
python -m pytest
python scripts/run_diploma_demo.py
python scripts/run_eval_gate.py
```

Run one deterministic mock scenario from Python:

```bash
python -c "from agent_coach.mock import build_mock_composition; c = build_mock_composition('grounded_success'); r = c.runner.run(c.request); print(r.answer_status, r.stop_reason.value)"
```

Run the localhost-only Mock Agent API:

```bash
agent-coach-api
```

The API binds to `127.0.0.1:8008` by default and rejects non-loopback bind
addresses. Swagger UI is available at `http://127.0.0.1:8008/docs`.

## Local Vector Example

```bash
python -c "from agent_coach.retrieval import build_local_vector_composition; c = build_local_vector_composition('How does photosynthesis store energy in glucose using chlorophyll?'); r = c.runner.run(c.request); print(r.answer_status, r.sources[0]['file_name'])"
```

Expected shape: the local-vector profile calls `rag.search`, returns a source
such as `photosynthesis-basics.md` and reports `local_zero` cost.

## Optional Live Provider

The live-provider profile is not used by CI or the Mock API. Install it only
when intentionally collecting opt-in evidence:

```bash
python -m pip install -e ".[live]"
```

Set provider configuration through environment variables documented in
[Live provider profile](docs/live_profile.md). Do not put API keys in Git, chat
or evidence files.

The D11 live eval runner requires explicit CLI opt-in:

```bash
python scripts/run_live_eval.py --allow-network --provider-opt-in --output ../agent-coach-live-eval-public.json
```

That forced-grounding live suite checks provider wiring, grounded synthesis and
citation behavior for pre-registered retrieval cases. It does not measure
autonomous planner tool-selection accuracy; that requires the separate
autonomous harness planned in D11 and live evidence collected after E1.

Scripted validation of the runner is offline and is not live evidence:

```bash
python scripts/run_live_eval.py --scripted
```

## Eval And Release Gates

Routine development checks:

```bash
python -m pytest
python -m ruff check .
python -m compileall src scripts
python scripts/check_contract_export.py
python scripts/check_openapi_snapshot.py
python scripts/check_drift_gate.py
python scripts/check_public_release.py
python scripts/check_d11_remediation_status.py
python scripts/run_eval_gate.py
```

Strict final release mode:

```bash
python scripts/check_public_release.py --release
```

The D11 offline eval gate freezes exactly 47 public synthetic cases. It reports
separate denominators for offline golden pass rate, retrieval top-1 accuracy,
retrieval negative rejection, adapter contract fail-closed behavior, security
containment and exact budget stop reasons. It requires 100% offline golden pass
rate, at least 80% retrieval top-1 accuracy and zero invalid or unknown
executed tools, security failures, hidden writes and grounded answers without
citation. The current offline gate reports
`gate_status: PASS`; `promotion_status` remains `HOLD` until valid opt-in live
evidence and clean fresh-clone release evidence are supplied for the reviewed
immutable commit.

## Profile Comparison

| Concern | Mock | Local vector | Optional live provider |
| --- | --- | --- | --- |
| Default | Yes | No | No |
| Network | No | No | Yes, only with opt-in |
| Data | Synthetic fixtures | Synthetic packaged corpus | Same corpus plus provider text |
| Tools | Read-only deterministic set | `rag.search` | `rag.search`, `learner.get_profile` |
| Models | Scripted local planner | Scripted local planner | Planner and synthesizer roles |
| State | In-memory only | In-process vector index | Stateless provider requests |
| Cost | `local_zero` | `local_zero` | `unknown` |
| Evidence | Deterministic | Deterministic | Non-deterministic, redacted |

## Review Materials

- [Architecture](docs/architecture.md)
- [API status](docs/api.md)
- [Core boundary](docs/core.md)
- [Mock adapters](docs/mock_adapters.md)
- [Local vector memory](docs/retrieval.md)
- [Live provider profile](docs/live_profile.md)
- [D11 eval gate](docs/eval_gate.md)
- [Tool SOP](docs/tool_sop.md)
- [Architecture review prompt](docs/prompts/architecture_review_prompt.md)
- [Diploma review kit](docs/review_kit.md)
- [Release checklist](docs/release_checklist.md)
- [Dependency notices](docs/dependency_notices.md)
- [Provenance](docs/provenance.md)
- [Drift gate](docs/drift_gate.md)
- [Implementation plan](docs/implementation_plan.md)
- [Adapter boundary ADR](docs/adr/0002-diploma-live-adapter-boundary.md)

The Tool SOP is generated from the currently advertised public `ToolSpec`
values and checked for drift:

```bash
python scripts/run_eval_gate.py --print-tool-sop
```

## Limitations

- localhost/in-process review surface only;
- ephemeral in-memory state only;
- read-only tools only;
- synthetic public corpus only;
- no production authentication, durable state, write tools, production MCP or
  deployment approval;
- local-vector retrieval is hashed lexical vector search, not neural
  embeddings;
- live-provider runs are opt-in, networked, variable and priced externally;
- unknown live pricing is reported as `unknown`, never as zero.
