# API

The local Mock Agent API is implemented as a deterministic localhost review
surface. It has the shape of a future Agent API, but it is not a production
service and does not simulate production authentication.

Run it with:

```bash
python -m pip install -e ".[dev]"
agent-coach-api
```

The default bind address is `127.0.0.1:8008`. Swagger UI is available at
`http://127.0.0.1:8008/docs`; the committed OpenAPI snapshot is
`docs/openapi.json`.

Implemented surface:

- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/demo/contracts`
- `GET /v1/demo/tools`
- `POST /v1/demo/tools/{tool_name}/call`
- `GET /healthz`
- `GET /readyz`

`POST /v1/runs` returns `202 Accepted` with `run_id`, `state`, a safe
`idempotency_key_id` and a polling URL. The demo executes deterministically in
process, so terminal states are usually available immediately from
`GET /v1/runs/{run_id}`. The lifecycle field is `state`; the API does not use
`status` for run lifecycle.

Idempotency uses the `Idempotency-Key` header. Reusing a key with the same
request returns the same run projection; reusing it with a different request
returns a `409 idempotency_conflict` error envelope. The raw header value is
never returned to clients.

Errors are returned as:

```json
{"error": {"code": "unknown_run", "message": "run_id is not known", "details": {}}}
```

The server enforces local demo payload limits on the actual ASGI request body,
including chunked requests without `Content-Length`. Startup rejects
non-loopback bind addresses. The API keeps state only in process memory and
returns no stack traces to clients.

Ephemeral run memory is capped at 256 stored runs. When the 257th unique run is
accepted, the oldest run and its matching idempotency mapping are evicted
together. `GET` for an evicted run returns the same bounded `404 unknown_run`
envelope as any unknown run. Recently retained idempotency keys keep the same
replay and conflict behavior described above.

Cancellation is reserved as `POST /v1/runs/{run_id}/cancel`, but it must not
appear in OpenAPI until a route exists in a later slice.
