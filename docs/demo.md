# Demo

The current demo surface is install/import, offline contract validation,
in-process deterministic mock adapter execution, optional in-process
local-vector retrieval, the D11 offline eval gate and a localhost-only Mock
Agent API with Swagger UI.

```bash
python -m pip install -e .
python -c "import agent_coach; print(agent_coach.__version__)"
python scripts/check_contract_export.py
python -c "from agent_coach.mock import build_mock_composition; c = build_mock_composition('grounded_success'); r = c.runner.run(c.request); print(r.answer_status, r.stop_reason.value)"
python scripts/run_diploma_demo.py
python scripts/run_eval_gate.py
```

Run the local Mock API:

```bash
python -m pip install -e ".[dev]"
agent-coach-api
```

Open Swagger UI at `http://127.0.0.1:8008/docs`, or call the API directly:

```bash
curl -s -X POST http://127.0.0.1:8008/v1/runs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-grounded" \
  -d "{\"scenario_id\":\"grounded_success\"}"
```

The exported contract bundle can be reviewed directly at
`contracts/agent_contracts/v1/agent_contract_bundle.json`.

Run the optional local-vector profile without network access:

```bash
python -c "from agent_coach.retrieval import build_local_vector_composition; c = build_local_vector_composition('How does photosynthesis store energy in glucose using chlorophyll?'); r = c.runner.run(c.request); print(r.answer_status, r.sources[0]['file_name'])"
```

Optional live-provider wiring is documented in `docs/live_profile.md`. It is
not part of the default demo path, is not used by the Mock API and requires
explicit opt-in when collecting D11 live evidence.

The synthetic mock fixtures live at `fixtures/mock_scenarios.json` for review
and are also packaged under `agent_coach.data` for wheel installs. They cover
the predeclared read-only mock tool subset plus controlled outcomes for
success, empty result, validation failure, timeout, rate limit, dependency
failure, security failure, oversized result, prompt injection and fake secret.

The Mock API stores runs only in process memory and exposes no production auth,
production data or durable state.

For final review, `scripts/run_diploma_demo.py` emits JSON evidence containing
the reviewed commit, dirty-worktree flag, mock profile, scenario id, contract
hash, advertised tools, terminal result projection and limitations.
`scripts/run_eval_gate.py` validates the frozen D11 offline suite and
thresholds. Use `docs/review_kit.md` and `docs/release_checklist.md` for the
full release gate.
