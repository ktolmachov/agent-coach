# Agent Coach Agent Instructions

This repository is a standalone public diploma demo. It is not a production
HomeTutor service and must not depend on a private HomeTutor checkout at
install, import, test or CI time.

## Invariants

- Keep Agent Core framework-independent when it is introduced: no FastAPI,
  HTTP clients, MCP SDK, provider clients, SQLite, filesystem fixture paths or
  environment reads inside core modules.
- Keep deterministic offline defaults for demo behavior.
- Do not add secrets, credentials, learner data, provider configuration,
  caches, database files or generated runtime state.
- Do not claim or imply production deployment approval.
- Work one slice at a time and stop after the promotion report.
- Run only targeted checks for the touched surface unless a reviewer asks for a
  broader suite.

## Slice Ownership

- D1: foundation only.
- D2: public contracts and provenance manifest.
- D3: framework-independent Agent Core.
- D4: deterministic mock adapters and fixtures.
- D5: local Mock Agent API.
- D6: parity and drift checks.
- D7: diploma review kit and release evidence.
- D8: local vector memory and retrieval.
