# API

The Agent API is not implemented in D1. OpenAPI is also not produced in D1.
There is no server command, no curl workflow and no Swagger UI yet.

The planned D5 local Mock Agent API will be a deterministic localhost demo with
future-shaped control endpoints and a separate demo inspection surface. Until
that slice lands, the only executable public check is package installation and
import.

Reserved future shape:

- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/demo/contracts`
- `GET /v1/demo/tools`
- `POST /v1/demo/tools/{tool_name}/call`
- `GET /healthz`
- `GET /readyz`

Cancellation is reserved as `POST /v1/runs/{run_id}/cancel`, but it must not
appear in OpenAPI until a route exists in a later slice.
