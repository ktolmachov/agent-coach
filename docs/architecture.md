# Architecture

The repository currently contains the public foundation, exported contract
artifacts, a framework-independent Agent Core, deterministic offline mock
adapters, a localhost-only Mock Agent API and an optional in-process
local-vector retrieval profile. The package is importable, runnable in process
and runnable as a local review API. It does not contain production network
transport, durable state or HomeTutor runtime code.

The planned architecture is intentionally layered:

```text
review tools, Swagger UI and curl
        |
local Mock Agent API / in-process composition
        |
explicit adapter profile
     /              \
 mock default     local-vector
        \              /
         AgentRunner
              |
        core ports
              |
     ToolExecutionPort
        /            \
 mock tools     LocalVectorRagTool
                       |
            EmbeddingPort + VectorStorePort
```

D2 freezes the public contract input for later layers. The exported contract
bundle is data only: it can be validated offline and carries source provenance,
but it does not import or execute HomeTutor runtime modules.

D4 adds an in-process deterministic composition: a scripted planner, mock tool
adapter, embedded security policy, deterministic clock, ephemeral run store and
synthetic public fixtures. Mock tools are selected from the frozen read-only D2
contract bundle and checked against their advertised schemas.

D5 adds a FastAPI layer over that composition. The API owns HTTP schemas,
idempotency memory, error envelopes, OpenAPI generation, request-size
enforcement and loopback-only startup validation. Agent Core logic remains
outside the API layer.

D8 adds a local-vector profile behind the same `rag.search` contract. The
hashed embedder and in-memory cosine store implement retrieval ports outside
Core. The Mock API still defaults to the deterministic mock profile. This is
not a production vector database.

Future production use is outside this repository's current authority. A later
architecture decision would be required before replacing the diploma mock
adapters with network, durable-state or authenticated adapters.

## Current Boundaries

- Runtime dependencies are limited to the local API layer.
- Core modules live under `src/agent_coach/core/` and depend only on the Python
  standard library plus package-owned modules.
- Mock modules live under `src/agent_coach/mock/` and depend only on the core,
  the Python standard library and package-owned synthetic fixtures.
- Retrieval modules live under `src/agent_coach/retrieval/` and depend only on
  the core, the Python standard library and the packaged public corpus.
- API modules live under `src/agent_coach/api/` and compose the core/mock
  runtime through package APIs.
- The core exposes explicit ports for planning, message building, security,
  tool execution, usage accounting, clock and run storage.
- The only server entry point defaults to `127.0.0.1:8008` and rejects
  non-loopback bind addresses.
- No write-enabled tool is advertised by the deterministic mock composition.
- The API exposes no production authentication simulation and keeps run state
  in process-local memory only.
- No private HomeTutor checkout is needed to install, import or validate the
  exported contracts.
- Public documentation is sanitized and self-contained.
