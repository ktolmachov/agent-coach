# Architecture

D1 implements only the public repository foundation. The package is importable,
but it contains no Agent Core, adapters, contracts, fixtures, API server or
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

Future production use is outside this repository's current authority. A later
architecture decision would be required before replacing the diploma mock
adapters with network, durable-state or authenticated adapters.

## D1 Boundaries

- The package has zero runtime dependencies.
- Core modules are not present yet.
- No network listener is implemented.
- No private HomeTutor checkout is needed to install or import this package.
- Public documentation is sanitized and self-contained.
