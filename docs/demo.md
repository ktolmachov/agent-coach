# Demo

The current demo surface is install/import plus offline contract validation.

```bash
python -m pip install -e .
python -c "import agent_coach; print(agent_coach.__version__)"
python scripts/check_contract_export.py
```

The exported contract bundle can be reviewed directly at
`contracts/agent_contracts/v1/agent_contract_bundle.json`.

The interactive deterministic demo is planned for later slices after Agent
Core, mock adapters and the local Mock Agent API exist.
