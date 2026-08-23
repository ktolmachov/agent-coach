# Architecture

The repository currently contains the public foundation, exported contract
artifacts and a framework-independent Agent Core. The package is importable,
but it does not yet contain adapters, runtime replay fixtures, an API server or
HomeTutor runtime code.

The planned architecture is intentionally layered:

```text
review tools and local API
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

Future production use is outside this repository's current authority. A later
architecture decision would be required before replacing the diploma mock
adapters with network, durable-state or authenticated adapters.

## Current Boundaries

- The package has zero runtime dependencies.
- Core modules live under `src/agent_coach/core/` and depend only on the Python
  standard library plus package-owned modules.
- The core exposes explicit ports for planning, message building, security,
  tool execution, usage accounting, clock and run storage.
- No network listener is implemented.
- No private HomeTutor checkout is needed to install, import or validate the
  exported contracts.
- Public documentation is sanitized and self-contained.
