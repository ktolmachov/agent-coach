"""FastAPI app factory for the local Mock Agent API."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agent_coach.api.models import (
    API_VERSION,
    MAX_REQUEST_BYTES,
    ContractResponse,
    ErrorResponse,
    HealthResponse,
    RunAcceptedResponse,
    RunCreateRequest,
    RunStatusResponse,
    ToolCallRequest,
    ToolCallResponse,
    ToolListResponse,
)
from agent_coach.api.service import ApiError, MockApiService


class PayloadLimitMiddleware:
    """Enforce request size on the actual ASGI receive stream."""

    def __init__(self, app, *, limit_bytes: int) -> None:
        self._app = app
        self._limit_bytes = limit_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        content_length = _content_length(scope)
        if content_length is not None and content_length > self._limit_bytes:
            await _send_payload_too_large(send, self._limit_bytes)
            return
        total = 0
        buffered: list[dict[str, Any]] = []

        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                break
            total += len(message.get("body") or b"")
            if total > self._limit_bytes:
                await _send_payload_too_large(send, self._limit_bytes)
                return
            if not message.get("more_body", False):
                break

        async def replay_receive():
            if not buffered:
                return {"type": "http.request", "body": b"", "more_body": False}
            return buffered.pop(0)

        await self._app(scope, replay_receive, send)


def create_app() -> FastAPI:
    """Create a fresh process-local Mock API application."""

    app = FastAPI(
        title="Agent Coach Local Mock API",
        summary="Deterministic localhost-only diploma review API.",
        version=API_VERSION,
        docs_url="/docs",
        redoc_url=None,
    )
    service = MockApiService()
    app.add_middleware(PayloadLimitMiddleware, limit_bytes=MAX_REQUEST_BYTES)

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        del request
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        del request
        return error_response(
            ApiError(
                422,
                "validation_error",
                "request validation failed",
                details={"errors": _validation_details(exc)},
            )
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        del request, exc
        return error_response(ApiError(500, "internal_error", "internal error"))

    @app.get(
        "/healthz",
        response_model=HealthResponse,
        responses={500: {"model": ErrorResponse}},
        tags=["operations"],
    )
    def healthz() -> HealthResponse:
        return HealthResponse(
            ok=True,
            api_version=API_VERSION,
            auth="none",
            production_auth=False,
            state_store="ephemeral_in_memory",
        )

    @app.get(
        "/readyz",
        response_model=HealthResponse,
        responses={500: {"model": ErrorResponse}},
        tags=["operations"],
    )
    def readyz() -> HealthResponse:
        return healthz()

    @app.post(
        "/v1/runs",
        response_model=RunAcceptedResponse,
        status_code=202,
        responses={
            409: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
        tags=["runs"],
    )
    def create_run(
        body: RunCreateRequest,
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
            description="Optional deterministic demo idempotency key.",
        ),
    ) -> RunAcceptedResponse:
        return service.create_run(body, idempotency_key=idempotency_key)

    @app.get(
        "/v1/runs/{run_id}",
        response_model=RunStatusResponse,
        responses={
            404: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
        tags=["runs"],
    )
    def get_run(run_id: str) -> RunStatusResponse:
        return service.get_run(run_id)

    @app.get(
        "/v1/demo/contracts",
        response_model=ContractResponse,
        responses={500: {"model": ErrorResponse}},
        tags=["demo"],
    )
    def get_contracts() -> dict[str, Any]:
        return service.contracts()

    @app.get(
        "/v1/demo/tools",
        response_model=ToolListResponse,
        responses={500: {"model": ErrorResponse}},
        tags=["demo"],
    )
    def list_tools() -> dict[str, Any]:
        return service.list_tools()

    @app.post(
        "/v1/demo/tools/{tool_name}/call",
        response_model=ToolCallResponse,
        responses={
            404: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
        tags=["demo"],
    )
    def call_tool(tool_name: str, body: ToolCallRequest) -> ToolCallResponse:
        return service.call_tool(tool_name, body)

    return app


def error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


def _validation_details(exc: RequestValidationError) -> dict[str, Any]:
    return {"count": len(exc.errors())}


def _content_length(scope) -> int | None:
    for name, value in scope.get("headers") or ():
        if name == b"content-length":
            try:
                length = int(value.decode("ascii"))
            except ValueError:
                return None
            return max(length, 0)
    return None


async def _send_payload_too_large(send, limit_bytes: int) -> None:
    payload = {
        "error": {
            "code": "payload_too_large",
            "message": "request body exceeds the local demo payload limit",
            "details": {"limit_bytes": limit_bytes},
        }
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
