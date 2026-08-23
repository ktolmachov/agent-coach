# Agent Coach

Agent Coach is a standalone deterministic diploma demo repository. It now
contains the public repository foundation, exported versioned contract
artifacts, a framework-independent Agent Core and offline deterministic mock
adapters, and a local Mock Agent API for review.

Implemented so far:

- installable Python package skeleton with `src` layout;
- Apache-2.0 package metadata;
- smoke test for package import and version metadata;
- Ruff, Pytest and compile checks configuration;
- least-privilege CI workflow;
- public-safe architecture, provenance and implementation-plan documents;
- exported Agent contract bundle `agent-contracts/1.0.0`;
- deterministic contract validation vectors and export manifest;
- public verifier for contract hash, manifest and provenance integrity.
- framework-independent Agent Core behind explicit ports;
- focused core tests for stop, security and contract-vector behavior.
- deterministic offline mock adapters and synthetic public fixtures;
- mock adapter tests for advertised schemas, controlled outcomes, security
  fixtures and deterministic repeatability.
- package data resources for wheel-installed offline mock runs.
- localhost-only FastAPI Mock Agent API with OpenAPI and Swagger UI.

The Mock API is a deterministic local review surface. It has no production
auth, no production data and no durable production state.

## Install

```bash
python -m pip install -e .
python -c "import agent_coach; print(agent_coach.__version__)"
```

Run the local Mock API:

```bash
python -m pip install -e ".[dev]"
agent-coach-api
```

By default the server binds to `127.0.0.1:8008`; non-loopback bind addresses
are rejected. Swagger UI is available at `http://127.0.0.1:8008/docs`.

## Development Checks

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m compileall src
python scripts/check_contract_export.py
python scripts/check_openapi_snapshot.py
```

Run one deterministic offline mock scenario from Python:

```bash
python -c "from agent_coach.mock import build_mock_composition; c = build_mock_composition('grounded_success'); r = c.runner.run(c.request); print(r.answer_status, r.stop_reason.value)"
```

The runtime dependencies are limited to the local API layer. Agent Core and mock
adapter modules remain framework-independent and do not import FastAPI.

## Contracts

The exported public contract lives at
`contracts/agent_contracts/v1/agent_contract_bundle.json`. Its canonical schema
hash is `218c90732c25ae2f9b26c4f5a9ea5ee81c28bf797299c99b53e310bf22315910`.
The export manifest records the source commit, source path, target path and
sha256 values for every exported file.

## Documentation

- [Architecture](docs/architecture.md)
- [API status](docs/api.md)
- [Core boundary](docs/core.md)
- [Mock adapters](docs/mock_adapters.md)
- [Demo status](docs/demo.md)
- [Provenance](docs/provenance.md)
- [Implementation plan](docs/implementation_plan.md)
- [Boundary ADR](docs/adr/0001-diploma-distribution-boundary.md)
