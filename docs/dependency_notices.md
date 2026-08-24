# Dependency Notices

Agent Coach is licensed under Apache-2.0. The current direct dependency set is
small and is declared in `pyproject.toml`.

## Runtime Dependencies

| Package | Purpose | License |
| --- | --- | --- |
| FastAPI | Localhost Mock Agent API framework | MIT |
| Uvicorn | Localhost ASGI server entry point | BSD-3-Clause |

## Development Dependencies

| Package | Purpose | License |
| --- | --- | --- |
| HTTPX | API test client support | BSD-3-Clause |
| Pytest | Public test suite | MIT |
| Ruff | Linting | MIT |

## Optional Live Extra

| Package | Purpose | License |
| --- | --- | --- |
| OpenAI Python SDK | Optional Responses API adapter for the live-provider profile | Apache-2.0 |

Install with `pip install -e ".[live]"`. The base diploma demo does not need
this extra. Do not commit API keys.

Transitive dependencies are installed by the Python package resolver and should
be reviewed from the resolved environment before creating a public release tag.
No dependency grants production deployment approval for this repository.
