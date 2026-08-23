# Agent Coach

Agent Coach is a standalone deterministic diploma demo repository. It now
contains the public repository foundation plus the first exported versioned
contract artifacts for offline review.

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

Planned later slices add framework-independent Agent Core, deterministic mock
adapters and a local Mock Agent API. Those pieces are not implemented yet.

## Install

```bash
python -m pip install -e .
python -c "import agent_coach; print(agent_coach.__version__)"
```

## Development Checks

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m compileall src
python scripts/check_contract_export.py
```

The project has no runtime dependencies. Development tools are declared only as
optional extras.

## Contracts

The exported public contract lives at
`contracts/agent_contracts/v1/agent_contract_bundle.json`. Its canonical schema
hash is `218c90732c25ae2f9b26c4f5a9ea5ee81c28bf797299c99b53e310bf22315910`.
The export manifest records the source commit, source path, target path and
sha256 values for every exported file.

## Documentation

- [Architecture](docs/architecture.md)
- [API status](docs/api.md)
- [Demo status](docs/demo.md)
- [Provenance](docs/provenance.md)
- [Implementation plan](docs/implementation_plan.md)
- [Boundary ADR](docs/adr/0001-diploma-distribution-boundary.md)
