# Architecture

The repository currently contains the public foundation and exported contract
artifacts. The package is importable, but it does not yet contain Agent Core,
adapters, runtime replay fixtures, an API server or HomeTutor runtime code.

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
- Core modules are not present yet.
- No network listener is implemented.
- No private HomeTutor checkout is needed to install, import or validate the
  exported contracts.
- Public documentation is sanitized and self-contained.
