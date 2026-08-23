# Deterministic Mock Adapters

D4 adds the offline composition used by the diploma review demo before any
local API server exists.

Implemented modules:

- `agent_coach.mock.fixtures` loads the package-owned synthetic fixture bundle
  from `agent_coach.data`.
- `agent_coach.mock.adapters` provides `DeterministicPlanner`,
  `MockToolAdapter`, `MockSecurityPolicy`, `DeterministicClock` and
  `EphemeralRunStore`.
- `agent_coach.mock.composition` wires those ports into `AgentRunner` through
  `build_mock_composition`.

The advertised mock tool subset is frozen in `fixtures/mock_scenarios.json`,
mirrored into wheel package data, and loaded from the packaged D2 contract
bundle resource:

- `learner.get_profile`
- `rag.search`
- `quiz.generate`
- `cards.get_due`
- `catalog.list`

All advertised tools are read-only. The mock composition does not expose
write-enabled tools, does not persist state outside process memory and does not
open network connections.

Controlled outcomes covered by fixtures:

- `success`
- `empty`
- `validation_failure`
- `timeout`
- `rate_limit`
- `dependency_failure`
- `security_failure`
- `oversized_result`
- `prompt_injection`
- `fake_secret`

Example:

```bash
python -c "from agent_coach.mock import build_mock_composition; c = build_mock_composition('grounded_success'); r = c.runner.run(c.request); print(r.answer_status, r.stop_reason.value)"
```

The fixture provenance is synthetic and public-safe: it contains no production
learner data, credentials, HomeTutor database content or HomeTutor runtime
dependency.

Focused tests compare packaged resources against the review artifacts, run a
tainted request through the store projection, assert every controlled outcome
category and verify stable golden projections for every scenario.
