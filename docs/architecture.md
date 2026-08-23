# Architecture

The repository currently contains the public foundation, exported contract
artifacts, a framework-independent Agent Core and deterministic offline mock
adapters. The package is importable and runnable in process, but it does not
contain an API server, network transport, durable state or HomeTutor runtime
code.

The planned architecture is intentionally layered:

```text
review tools and later local API
        |
composition root
        |
framework-independent Agent Core
        |
explicit ports
        |
deterministic mock adapters and synthetic fixtures
```

D2 freezes the public contract input for later layers. The exported contract
bundle is data only: it can be validated offline and carries source provenance,
but it does not import or execute HomeTutor runtime modules.

D4 adds an in-process deterministic composition: a scripted planner, mock tool
adapter, embedded security policy, deterministic clock, ephemeral run store and
synthetic public fixtures. Mock tools are selected from the frozen read-only D2
contract bundle and checked against their advertised schemas.

Future production use is outside this repository's current authority. A later
architecture decision would be required before replacing the diploma mock
adapters with network, durable-state or authenticated adapters.

## Current Boundaries

- The package has zero runtime dependencies.
- Core modules live under `src/agent_coach/core/` and depend only on the Python
  standard library plus package-owned modules.
- Mock modules live under `src/agent_coach/mock/` and depend only on the core,
  the Python standard library and package-owned synthetic fixtures.
- The core exposes explicit ports for planning, message building, security,
  tool execution, usage accounting, clock and run storage.
- No network listener is implemented.
- No write-enabled tool is advertised by the deterministic mock composition.
- No private HomeTutor checkout is needed to install, import or validate the
  exported contracts.
- Public documentation is sanitized and self-contained.
