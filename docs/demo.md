# Demo

The current demo surface is install/import, offline contract validation and
in-process deterministic mock adapter execution.

```bash
python -m pip install -e .
python -c "import agent_coach; print(agent_coach.__version__)"
python scripts/check_contract_export.py
python -c "from agent_coach.mock import build_mock_composition; c = build_mock_composition('grounded_success'); r = c.runner.run(c.request); print(r.answer_status, r.stop_reason.value)"
```

The exported contract bundle can be reviewed directly at
`contracts/agent_contracts/v1/agent_contract_bundle.json`.

The synthetic mock fixtures live at `fixtures/mock_scenarios.json` for review
and are also packaged under `agent_coach.data` for wheel installs. They cover
the predeclared read-only mock tool subset plus controlled outcomes for
success, empty result, validation failure, timeout, rate limit, dependency
failure, security failure, oversized result, prompt injection and fake secret.

The local Mock Agent API and Swagger UI are planned for D5. They are not
implemented yet.
