from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_coach.api import create_app
from agent_coach.api.models import (
    API_VERSION,
    MAX_REQUEST_BYTES,
    OPENAPI_VERSION,
    RunCreateRequest,
)
from agent_coach.api.server import DEFAULT_HOST, DEFAULT_PORT, build_arg_parser
from agent_coach.api.service import MAX_STORED_RUNS, ApiError, MockApiService

REPO_ROOT = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _create_run(
    client: TestClient,
    *,
    scenario_id: str = "grounded_success",
    key: str = "demo-key",
    **extra: object,
):
    body = {"scenario_id": scenario_id, **extra}
    return client.post("/v1/runs", json=body, headers={"Idempotency-Key": key})


def test_health_and_readyz_expose_no_production_auth() -> None:
    client = _client()

    for path in ("/healthz", "/readyz"):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert body == {
            "ok": True,
            "api_version": API_VERSION,
            "auth": "none",
            "production_auth": False,
            "state_store": "ephemeral_in_memory",
        }


def test_openapi_schema_matches_contract_surface_without_cancel_route() -> None:
    client = _client()
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"] == OPENAPI_VERSION
    assert schema["info"]["version"] == API_VERSION
    assert set(schema["paths"]) >= {
        "/healthz",
        "/readyz",
        "/v1/runs",
        "/v1/runs/{run_id}",
        "/v1/demo/contracts",
        "/v1/demo/tools",
        "/v1/demo/tools/{tool_name}/call",
    }
    assert "/v1/runs/{run_id}/cancel" not in schema["paths"]
    run_schema = json.dumps(schema["components"]["schemas"]["RunStatusResponse"])
    assert "status" not in run_schema
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert "ValidationError" not in schema["components"]["schemas"]
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            response = operation.get("responses", {}).get("422")
            if response is not None:
                content = response["content"]["application/json"]["schema"]
                assert content["$ref"] == "#/components/schemas/ErrorResponse"
    for schema_name in ("RunCreateRequest", "ToolCallRequest"):
        request_schema = schema["components"]["schemas"][schema_name]
        assert request_schema["additionalProperties"] is False


def test_create_and_get_run_use_state_lifecycle() -> None:
    client = _client()

    created = _create_run(client)

    assert created.status_code == 202
    accepted = created.json()
    assert accepted["state"] == "completed"
    assert accepted["ephemeral"] is True
    assert accepted["polling_url"] == f"/v1/runs/{accepted['run_id']}"
    assert "status" not in accepted

    fetched = client.get(accepted["polling_url"])
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["run_id"] == accepted["run_id"]
    assert body["state"] == "completed"
    assert body["result"]["answer_status"] == "grounded"
    assert body["result"]["success"] is True
    assert body["result"]["trace"]["run_id"] == accepted["run_id"]
    assert "status" not in body


def test_deterministic_duplicate_request_returns_same_run() -> None:
    client = _client()

    first = _create_run(client, key="same")
    second = _create_run(client, key="same")

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json()


def test_idempotency_key_is_not_reflected_to_client() -> None:
    client = _client()

    response = _create_run(client, key="token: DEMOSECRET123456")

    assert response.status_code == 202
    body = response.json()
    assert body["idempotency_key_id"].startswith("idem-")
    assert "idempotency_key" not in body
    assert "DEMOSECRET" not in response.text
    assert "token:" not in response.text


def test_idempotency_conflict_uses_error_envelope() -> None:
    client = _client()

    first = _create_run(client, key="conflict", scenario_id="grounded_success")
    second = _create_run(client, key="conflict", scenario_id="empty_cards")

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_conflict"
    assert "Traceback" not in second.text


def test_concurrent_idempotency_conflict_is_atomic() -> None:
    client = _client()
    key = "same-concurrent-key"

    def send(scenario_id: str):
        return _create_run(client, key=key, scenario_id=scenario_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(send, ("grounded_success", "empty_cards"))
        )

    statuses = sorted(response.status_code for response in responses)
    conflict_codes = [
        response.json()["error"]["code"]
        for response in responses
        if response.status_code == 409
    ]

    assert statuses == [202, 409]
    assert conflict_codes == ["idempotency_conflict"]


def test_run_store_capacity_evicts_oldest_run_and_idempotency_pair() -> None:
    service = MockApiService()
    created = [
        service.create_run(
            RunCreateRequest(
                scenario_id="grounded_success",
                question=f"question {index}",
            ),
            idempotency_key=f"capacity-{index}",
        )
        for index in range(MAX_STORED_RUNS + 1)
    ]
    first = created[0]
    recent = created[-1]

    assert len(service._runs) <= MAX_STORED_RUNS
    assert len(service._idempotency) <= MAX_STORED_RUNS
    with pytest.raises(ApiError) as exc_info:
        service.get_run(first.run_id)
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "unknown_run"

    replaced = service.create_run(
        RunCreateRequest(scenario_id="grounded_success", question="question 0"),
        idempotency_key="capacity-0",
    )
    replay = service.create_run(
        RunCreateRequest(
            scenario_id="grounded_success",
            question=f"question {MAX_STORED_RUNS}",
        ),
        idempotency_key=f"capacity-{MAX_STORED_RUNS}",
    )
    with pytest.raises(ApiError) as conflict_info:
        service.create_run(
            RunCreateRequest(
                scenario_id="grounded_success",
                question="different recent question",
            ),
            idempotency_key=f"capacity-{MAX_STORED_RUNS}",
        )

    assert replaced.run_id == first.run_id
    assert replay == recent
    assert conflict_info.value.status_code == 409
    assert conflict_info.value.code == "idempotency_conflict"
    assert len(service._runs) <= MAX_STORED_RUNS
    assert len(service._idempotency) <= MAX_STORED_RUNS


def test_evicted_run_get_returns_bounded_not_found() -> None:
    client = _client()
    created = [
        _create_run(client, key=f"http-capacity-{index}", question=f"question {index}")
        for index in range(MAX_STORED_RUNS + 1)
    ]
    first = created[0].json()

    response = client.get(first["polling_url"])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_run"
    assert "Traceback" not in response.text


def test_unknown_run_returns_bounded_not_found() -> None:
    response = _client().get("/v1/runs/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_run"
    assert "Traceback" not in response.text


def test_demo_contracts_are_exposed_for_review() -> None:
    response = _client().get("/v1/demo/contracts")

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == API_VERSION
    assert body["contract_schema_version"] == "agent-contracts/1.0.0"
    assert body["advertised_read_only_tools"] == [
        "learner.get_profile",
        "rag.search",
        "quiz.generate",
        "cards.get_due",
        "catalog.list",
    ]


def test_demo_tools_list_contract_subset() -> None:
    response = _client().get("/v1/demo/tools")

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == API_VERSION
    assert [tool["name"] for tool in body["tools"]] == [
        "learner.get_profile",
        "rag.search",
        "quiz.generate",
        "cards.get_due",
        "catalog.list",
    ]
    assert {tool["access"] for tool in body["tools"]} == {"read"}


def test_valid_tool_call_returns_sanitized_result() -> None:
    response = _client().post(
        "/v1/demo/tools/rag.search/call",
        json={
            "scenario_id": "grounded_success",
            "args": {"query": "photosynthesis", "top_k": 2},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_name"] == "rag.search"
    assert body["ok"] is True
    assert body["meta"]["has_evidence"] is True


def test_unknown_tool_returns_not_found() -> None:
    response = _client().post(
        "/v1/demo/tools/write.grade/call",
        json={"args": {}},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tool"


def test_forbidden_identity_args_are_rejected_before_tool_execution() -> None:
    response = _client().post(
        "/v1/demo/tools/rag.search/call",
        json={"args": {"query": "x", "run_id": "attacker-run"}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "forbidden_identity_args"


def test_schema_validation_uses_error_envelope() -> None:
    response = _client().post("/v1/runs", json={"scenario_id": "../bad"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "field",
    ["run_id", "user_id", "session_id", "query_options", "unexpected"],
)
def test_run_create_rejects_top_level_extra_fields(field: str) -> None:
    response = _client().post(
        "/v1/runs",
        json={"scenario_id": "grounded_success", field: "attacker"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "field",
    ["run_id", "user_id", "session_id", "query_options", "unexpected"],
)
def test_tool_call_rejects_top_level_extra_fields(field: str) -> None:
    response = _client().post(
        "/v1/demo/tools/rag.search/call",
        json={"args": {"query": "photosynthesis"}, field: "attacker"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_injection_and_secret_redaction_through_api() -> None:
    client = _client()

    injection = _create_run(client, scenario_id="prompt_injection", key="inj")
    secret = _create_run(client, scenario_id="fake_secret", key="secret")

    for created in (injection, secret):
        assert created.status_code == 202
        fetched = client.get(created.json()["polling_url"])
        serialized = json.dumps(fetched.json(), ensure_ascii=False)
        assert "Ignore previous" not in serialized
        assert "system prompt" not in serialized
        assert "DEMOSECRET" not in serialized
        assert "DEMOTOKEN" not in serialized


def test_timeout_rate_dependency_errors_are_bounded_results() -> None:
    client = _client()

    for scenario_id in ("timeout", "rate_limit", "dependency_failure"):
        created = _create_run(client, scenario_id=scenario_id, key=scenario_id)
        assert created.status_code == 202
        fetched = client.get(created.json()["polling_url"])
        body = fetched.json()
        assert body["state"] == "completed"
        assert body["result"]["answer_status"] == "abstain"
        assert "Traceback" not in fetched.text


def test_payload_and_result_size_limits_are_enforced() -> None:
    client = _client()
    oversized_payload = {
        "scenario_id": "grounded_success",
        "question": "x" * MAX_REQUEST_BYTES,
    }

    payload_response = client.post("/v1/runs", json=oversized_payload)
    result_response = _create_run(
        client,
        scenario_id="grounded_success",
        key="tiny-result",
        result_limit_chars=1000,
    )

    assert payload_response.status_code == 413
    assert payload_response.json()["error"]["code"] == "payload_too_large"
    assert result_response.status_code == 413
    assert result_response.json()["error"]["code"] == "result_too_large"


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
def test_asgi_payload_limit_counts_actual_body_not_headers(headers) -> None:
    status, body = asyncio.run(_asgi_post_oversized_run(headers=headers))

    assert status == 413
    assert body["error"]["code"] == "payload_too_large"


def test_live_chunked_payload_limit_is_enforced() -> None:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_coach.api", "--port", str(port)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_health(port)
        response = _send_chunked_oversized_run(port)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    assert b" 413 " in response.split(b"\r\n", 1)[0]
    assert b"payload_too_large" in response


def test_localhost_safe_startup_defaults() -> None:
    args = build_arg_parser().parse_args([])

    assert DEFAULT_HOST == "127.0.0.1"
    assert DEFAULT_PORT == 8008
    assert args.host == DEFAULT_HOST
    assert args.port == DEFAULT_PORT


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.50", "example.test"])
def test_startup_rejects_non_loopback_hosts(host: str) -> None:
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["--host", host])


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_startup_accepts_loopback_hosts(host: str) -> None:
    args = build_arg_parser().parse_args(["--host", host])

    assert args.host == host


def test_openapi_snapshot_is_current() -> None:
    expected = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    actual = (REPO_ROOT / "docs" / "openapi.json").read_text(encoding="utf-8")

    assert actual == expected


async def _asgi_post_oversized_run(*, headers):
    body = json.dumps(
        {"scenario_id": "grounded_success", "question": "x" * MAX_REQUEST_BYTES}
    ).encode("utf-8")
    messages = [
        {"type": "http.request", "body": body[:100], "more_body": True},
        {"type": "http.request", "body": body[100:], "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await create_app()(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/runs",
            "raw_path": b"/v1/runs",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json"), *headers],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8008),
        },
        receive,
        send,
    )
    status = next(
        message["status"]
        for message in sent
        if message["type"] == "http.response.start"
    )
    raw_body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    return status, json.loads(raw_body.decode("utf-8"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_for_health(port: int) -> None:
    deadline = time.time() + 10
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz", timeout=0.5
            ) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - retry until server is ready
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"server did not become ready: {last_error}")


def _send_chunked_oversized_run(port: int) -> bytes:
    body = json.dumps(
        {"scenario_id": "grounded_success", "question": "x" * 100_050}
    ).encode("utf-8")
    request = (
        f"POST /v1/runs HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Transfer-Encoding: chunked\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"
    ).encode("ascii")
    chunk = bytearray()
    for index in range(0, len(body), 1024):
        part = body[index : index + 1024]
        chunk.extend(f"{len(part):X}\r\n".encode("ascii"))
        chunk.extend(part)
        chunk.extend(b"\r\n")
    chunk.extend(b"0\r\n\r\n")
    with socket.create_connection(("127.0.0.1", port), timeout=3) as client:
        client.sendall(request + chunk)
        client.settimeout(3)
        response = bytearray()
        while True:
            try:
                data = client.recv(4096)
            except TimeoutError:
                break
            if not data:
                break
            response.extend(data)
            if b"payload_too_large" in response:
                break
        return bytes(response)
