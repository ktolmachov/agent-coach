"""Ephemeral service layer for the local Mock Agent API."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from threading import Lock
from typing import Any

from agent_coach.api.models import (
    API_VERSION,
    FORBIDDEN_IDENTITY_ARGS,
    MAX_RESULT_LIMIT_CHARS,
    AgentResultResponse,
    AgentStepResponse,
    ApiRunState,
    RunAcceptedResponse,
    RunCreateRequest,
    RunStatusResponse,
    ToolCallRequest,
    ToolCallResponse,
)
from agent_coach.core.contracts import (
    CONTRACT_SCHEMA_HASH,
    CONTRACT_SCHEMA_VERSION,
    AgentRunResult,
    RunRequest,
    ToolContext,
    ToolResult,
)
from agent_coach.core.security import trace_text
from agent_coach.mock import (
    MockSecurityPolicy,
    MockToolAdapter,
    advertised_mock_tools,
    build_mock_composition,
    load_mock_fixture,
)


class ApiError(Exception):
    """Bounded API failure that renders as a public error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = {} if details is None else dict(details)


@dataclass(frozen=True)
class StoredRun:
    run_id: str
    scenario_id: str
    state: ApiRunState
    request_fingerprint: str
    idempotency_key_id: str
    result_limit_chars: int
    result: AgentRunResult


class MockApiService:
    """Process-local deterministic API service with idempotency memory."""

    def __init__(self) -> None:
        self._runs: dict[str, StoredRun] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = Lock()

    def create_run(
        self,
        request: RunCreateRequest,
        *,
        idempotency_key: str | None,
    ) -> RunAcceptedResponse:
        fingerprint = _fingerprint_request(request)
        normalized_key = _normalize_idempotency_key(idempotency_key, fingerprint)
        with self._lock:
            existing_run_id = self._idempotency.get(normalized_key)
            if existing_run_id is not None:
                existing = self._runs[existing_run_id]
                if existing.request_fingerprint != fingerprint:
                    raise ApiError(
                        409,
                        "idempotency_conflict",
                        "idempotency key was already used for a different request",
                    )
                return _accepted(existing)
            composition = _build_composition_or_422(request.scenario_id)
            run_id = _run_id_for(normalized_key, fingerprint)
            question = request.question or composition.scenario.question
            run_request = RunRequest(
                question=question,
                user_id="demo-user",
                session_id="demo-session",
                run_id=run_id,
                query_options={
                    "adapter_profile": "mock",
                    "scenario_id": request.scenario_id,
                },
                limits=composition.request.limits,
            )
            result = composition.runner.run(run_request)
            stored = StoredRun(
                run_id=run_id,
                scenario_id=request.scenario_id,
                state=_api_state_for_result(result),
                request_fingerprint=fingerprint,
                idempotency_key_id=_safe_idempotency_key_id(normalized_key),
                result_limit_chars=request.result_limit_chars,
                result=result,
            )
            _ensure_json_size(_run_status(stored), request.result_limit_chars)
            self._runs[run_id] = stored
            self._idempotency[normalized_key] = run_id
            return _accepted(stored)

    def get_run(self, run_id: str) -> RunStatusResponse:
        with self._lock:
            stored = self._runs.get(run_id)
        if stored is None:
            raise ApiError(404, "unknown_run", "run_id is not known")
        status = _run_status(stored)
        _ensure_json_size(status, stored.result_limit_chars)
        return status

    def list_tools(self) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "tools": [_tool_projection(tool) for tool in advertised_mock_tools()],
        }

    def contracts(self) -> dict[str, Any]:
        fixture = load_mock_fixture()
        bundle = _contract_bundle()
        return {
            "api_version": API_VERSION,
            "contract_schema_version": CONTRACT_SCHEMA_VERSION,
            "contract_schema_hash": CONTRACT_SCHEMA_HASH,
            "fixture_schema_version": fixture.schema_version,
            "advertised_read_only_tools": list(fixture.advertised_read_only_tools),
            "controlled_outcomes": list(fixture.controlled_outcomes),
            "contracts": bundle["contracts"],
        }

    def call_tool(self, tool_name: str, request: ToolCallRequest) -> ToolCallResponse:
        if FORBIDDEN_IDENTITY_ARGS.intersection(request.args):
            raise ApiError(
                422,
                "forbidden_identity_args",
                "tool arguments must not include harness identity fields",
                details={"forbidden": sorted(FORBIDDEN_IDENTITY_ARGS)},
            )
        composition = _build_composition_or_422(request.scenario_id)
        tool_by_name = {tool.name: tool for tool in composition.tools}
        tool = tool_by_name.get(tool_name)
        if tool is None:
            raise ApiError(404, "unknown_tool", "tool_name is not advertised")
        security = MockSecurityPolicy()
        try:
            security.validate_tool_args(tool, request.args)
        except Exception as exc:  # noqa: BLE001 - security rejects untrusted payloads
            raise ApiError(
                422,
                "schema_validation_failed",
                trace_text(exc),
            ) from None
        context = ToolContext(
            user_id="demo-user",
            question=composition.scenario.question,
            query_options={
                "adapter_profile": "mock",
                "scenario_id": request.scenario_id,
            },
            session_id="demo-session",
            run_id="demo-tool-call",
        )
        raw = MockToolAdapter(composition.scenario).execute(tool, request.args, context)
        result = security.secure_tool_result(raw)
        if not isinstance(result, ToolResult):
            raise ApiError(500, "internal_error", "tool adapter returned invalid data")
        response = ToolCallResponse(
            api_version=API_VERSION,
            tool_name=tool.name,
            ok=result.ok,
            data=result.data,
            error=result.error,
            meta=dict(result.meta),
        )
        _ensure_json_size(response, request.result_limit_chars)
        return response


def _build_composition_or_422(scenario_id: str):
    try:
        return build_mock_composition(scenario_id)
    except ValueError as exc:
        raise ApiError(
            422,
            "unknown_scenario",
            trace_text(exc),
            details={"scenario_id": scenario_id},
        ) from None


def _accepted(stored: StoredRun) -> RunAcceptedResponse:
    return RunAcceptedResponse(
        api_version=API_VERSION,
        run_id=stored.run_id,
        state=stored.state,
        idempotency_key_id=stored.idempotency_key_id,
        polling_url=f"/v1/runs/{stored.run_id}",
        ephemeral=True,
    )


def _run_status(stored: StoredRun) -> RunStatusResponse:
    return RunStatusResponse(
        api_version=API_VERSION,
        run_id=stored.run_id,
        state=stored.state,
        scenario_id=stored.scenario_id,
        result=_result_projection(stored.result),
    )


def _result_projection(result: AgentRunResult) -> AgentResultResponse:
    return AgentResultResponse(
        answer=result.answer,
        answer_status=result.answer_status,
        success=result.success,
        stop_reason=result.stop_reason.value,
        sources=result.sources,
        trace=dict(result.trace),
        steps=[
            AgentStepResponse(
                step_index=step.step_index,
                state=step.state.value,
                tool_name=step.tool_name,
                tool_args=step.tool_args,
                tool_ok=(
                    step.tool_result.ok if step.tool_result is not None else None
                ),
                tool_error=(
                    step.tool_result.error if step.tool_result is not None else None
                ),
                error=step.error,
            )
            for step in result.steps
        ],
    )


def _api_state_for_result(result: AgentRunResult) -> ApiRunState:
    if result.stop_reason.is_success:
        return ApiRunState.COMPLETED
    return ApiRunState.FAILED


def _fingerprint_request(request: RunCreateRequest) -> str:
    return _sha256_json(
        {
            "scenario_id": request.scenario_id,
            "question": request.question,
            "result_limit_chars": request.result_limit_chars,
        }
    )


def _normalize_idempotency_key(raw: str | None, fingerprint: str) -> str:
    key = (raw or "").strip()
    if not key:
        return f"body:{fingerprint[:32]}"
    if len(key) > 120:
        raise ApiError(422, "invalid_idempotency_key", "idempotency key is too long")
    return key


def _run_id_for(idempotency_key: str, fingerprint: str) -> str:
    return f"mock-{_sha256_json({'key': idempotency_key, 'body': fingerprint})[:16]}"


def _safe_idempotency_key_id(idempotency_key: str) -> str:
    return f"idem-{_sha256_json({'key': idempotency_key})[:16]}"


def _tool_projection(tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "when_to_use": tool.when_to_use,
        "args_schema": tool.args_schema,
        "access": tool.access.value,
        "idempotent": tool.idempotent,
        "limits": dict(tool.limits),
    }


def _contract_bundle() -> dict[str, Any]:
    text = (
        resources.files("agent_coach.data")
        .joinpath("agent_contract_bundle.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def _ensure_json_size(model: Any, limit_chars: int) -> None:
    limit = min(max(limit_chars, 0), MAX_RESULT_LIMIT_CHARS)
    payload = model.model_dump(mode="json") if hasattr(model, "model_dump") else model
    size = len(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if size > limit:
        raise ApiError(
            413,
            "result_too_large",
            "response projection exceeds the requested result limit",
            details={"limit_chars": limit, "actual_chars": size},
        )


def _sha256_json(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
