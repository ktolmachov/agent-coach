# Agent Coach

Agent Coach is a standalone deterministic diploma demo repository. D1 provides
only the public foundation needed to continue the planned D2-D7 implementation
inside this repository.

Implemented in D1:

- installable Python package skeleton with `src` layout;
- Apache-2.0 package metadata;
- smoke test for package import and version metadata;
- Ruff, Pytest and compile checks configuration;
- least-privilege CI workflow;
- public-safe architecture, provenance and implementation-plan documents.

Planned later slices add contracts, framework-independent Agent Core,
deterministic mock adapters and a local Mock Agent API. Those pieces are not
implemented in D1.

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
```

The project has no runtime dependencies in D1. Development tools are declared
only as optional extras.

## Documentation

- [Architecture](docs/architecture.md)
- [API status](docs/api.md)
- [Demo status](docs/demo.md)
- [Provenance](docs/provenance.md)
- [Implementation plan](docs/implementation_plan.md)
- [Boundary ADR](docs/adr/0001-diploma-distribution-boundary.md)
