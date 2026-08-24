# Live Provider Profile

D9 adds an optional `live_provider` composition. It is not the default diploma
profile. The Mock Agent API, CI and `scripts/run_diploma_demo.py` stay on the
deterministic mock adapters.

## Boundary

```text
explicit live_provider composition
        |
AgentRunner
        |
OpenAIResponsesPlanner  -->  official OpenAI Python SDK / Responses API
        |
ToolExecutionPort
   /                    \
LocalVectorRagTool   public demo learner.get_profile
```

Agent Core remains the only orchestration loop. The official SDK is a provider
adapter, not a second runner. LangGraph and the OpenAI Agents SDK are not used.

The SDK is an optional extra:

```bash
python -m pip install -e ".[live]"
```

Base install, `[dev]` install and offline CI do not require the SDK, a network
or an API key. Missing SDK or `AGENT_COACH_LIVE_API_KEY` fails closed with a
bounded configuration error. The live profile never silently substitutes the
mock planner.

## Model routing

Trusted config selects two roles:

- `planner` — sees the question, advertised tool schemas and budget/tool state
  and may emit one native function call;
- `synthesizer` — after a successful tool observation, sees only safe grounded
  context and writes the final answer.

Default model ids are distinct (`gpt-4.1-mini` and `gpt-4.1`). If both roles
are configured with the same model id, routing records
`routing_status=degraded_same_model` and the two-model diploma requirement is
not closed.

Routing is an explicit policy: planner until a successful tool observation
exists, then synthesizer. A no-tool planner response is terminal and returns
to Agent Core as the final answer or abstention; it is not treated as proof
that both roles ran. Routing does not inspect model-name substrings.

## Native function calling

Advertised tools are converted from the frozen `ToolSpec` JSON Schema into
Responses `type=function` tools. The adapter requests sequential tool
selection (`parallel_tool_calls=false`, `tool_choice=auto`) and disables
provider-side response storage (`store=false`) while requesting
`include=["reasoning.encrypted_content"]` so stateless reasoning continuation
can replay opaque reasoning items. Multiple tool calls in one provider response
are rejected. Malformed JSON, missing `call_id`, missing function-call
`response_id`, unsupported `response.output` item types and synthesizer tool
calls fail closed. Provider responses must carry explicit `status=completed`;
missing, failed, incomplete or unknown statuses fail closed with bounded
errors. Unknown tools and invalid arguments use the existing Core stop paths
and are not executed.

The next provider turn is stateless: it replays the original input and every
bounded `response.output` item, then sends the matching `function_call_output`
with the same `call_id`, without using server-side `previous_response_id`.
Reasoning items and encrypted reasoning content are preserved exactly for
replay but are not exposed in public traces. Assistant output item `phase`
values are also preserved unchanged during manual replay. Replay-critical
provider output is never silently truncated or partially dropped; oversized
replay fails closed before another provider request is created. Malformed
replay items, missing item `type`, missing reasoning `encrypted_content` and
replay output that omits the matching function call fail closed. Replay
diagnostics use static field labels and do not echo provider-controlled mapping
keys. Raw provider payloads and chain-of-thought are not stored in traces. API
keys never appear in `repr`, traces, exceptions or public results. API base
values, including host and path, and model ids are validated and sanitized
before public config projection.

## Budgets

The live composition sets bounded run limits by default:

- `max_steps=6`;
- `max_time_sec=60`;
- `max_tokens=4000`;
- positive cost caps fail closed while cloud pricing is unknown.

Each planner call receives a compact `Budget state` input with remaining steps,
time, token and cost fields from Agent Core. The live composition also rejects
questions longer than `AGENT_COACH_LIVE_MAX_QUESTION_CHARS` before any provider
request is created. Agent Core rechecks time, token and cost limits after
provider usage is accounted and before accepting a final answer or executing a
tool call. Provider usage counters must be typed non-negative integers;
malformed counters fail closed instead of being coerced to zero. Valid provider
usage is counted as at least `prompt_tokens + completion_tokens` even when a
lower `total_tokens` is reported. If the planner response has no tool call,
the adapter returns control to Agent Core instead of making an internal
synthesizer request, so hard token and time limits are checked before any next
provider call. Provider final text is also bounded locally from
`AGENT_COACH_LIVE_MAX_OUTPUT_TOKENS`; oversized responses fail closed even if a
scripted or malicious provider ignores the remote `max_output_tokens` setting.

## Credentials

Do not put a key in chat, Git or evidence files. Locally you may set:

```text
AGENT_COACH_LIVE_API_KEY
AGENT_COACH_PLANNER_MODEL
AGENT_COACH_SYNTHESIZER_MODEL
AGENT_COACH_LIVE_API_BASE
AGENT_COACH_LIVE_TIMEOUT_SEC
AGENT_COACH_LIVE_MAX_RETRIES
AGENT_COACH_LIVE_MAX_OUTPUT_TOKENS
AGENT_COACH_LIVE_COST_CAP_USD
AGENT_COACH_LIVE_MAX_QUESTION_CHARS
AGENT_COACH_LIVE_MAX_RUN_TOKENS
AGENT_COACH_LIVE_RUN_TIME_LIMIT_SEC
```

A positive cost cap fails closed because this demo does not know cloud unit
prices and will not invent them. Reported `cost_status` stays `unknown`.

Offline proof for D9 is the scripted Responses client in tests. A live network
run is optional reviewer evidence and is not required to promote this slice.
D11 may still hold if live provider evidence is missing.

## Limitations

- localhost/in-process only;
- read-only advertised tools;
- no production auth or durable provider session store;
- hashed local-vector retrieval behind `rag.search` is not a neural embedding
  model;
- the public API still defaults to the mock profile;
- this is not production deployment approval.
