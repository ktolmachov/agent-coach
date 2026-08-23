"""HTTP schemas for the local Mock Agent API."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "agent-coach-api/1.0.0"
OPENAPI_VERSION = "3.1.0"
MAX_REQUEST_BYTES = 4096
DEFAULT_RESULT_LIMIT_CHARS = 16000
MAX_RESULT_LIMIT_CHARS = 32000
FORBIDDEN_IDENTITY_ARGS = frozenset(
    {"run_id", "user_id", "session_id", "query_options"}
)


class ApiRunState(StrEnum):
    """Future-shaped public run lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorEnvelope


class HealthResponse(BaseModel):
    ok: bool
    api_version: str
    auth: Literal["none"]
    production_auth: Literal[False]
    state_store: Literal["ephemeral_in_memory"]


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(
        default="grounded_success",
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9_:-]+$",
    )
    question: str | None = Field(default=None, max_length=500)
    result_limit_chars: int = Field(
        default=DEFAULT_RESULT_LIMIT_CHARS,
        ge=1000,
        le=MAX_RESULT_LIMIT_CHARS,
    )


class RunAcceptedResponse(BaseModel):
    api_version: str
    run_id: str
    state: ApiRunState
    idempotency_key_id: str
    polling_url: str
    ephemeral: Literal[True]


class AgentStepResponse(BaseModel):
    step_index: int
    state: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_ok: bool | None = None
    tool_error: str | None = None
    error: str | None = None


class AgentResultResponse(BaseModel):
    answer: str
    answer_status: str
    success: bool
    stop_reason: str
    sources: list[dict[str, Any]]
    trace: dict[str, Any]
    steps: list[AgentStepResponse]


class RunStatusResponse(BaseModel):
    api_version: str
    run_id: str
    state: ApiRunState
    scenario_id: str
    result: AgentResultResponse | None = None


class ToolListResponse(BaseModel):
    api_version: str
    tools: list[dict[str, Any]]


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)
    scenario_id: str = Field(
        default="grounded_success",
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9_:-]+$",
    )
    result_limit_chars: int = Field(
        default=DEFAULT_RESULT_LIMIT_CHARS,
        ge=1000,
        le=MAX_RESULT_LIMIT_CHARS,
    )


class ToolCallResponse(BaseModel):
    api_version: str
    tool_name: str
    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any]


class ContractResponse(BaseModel):
    api_version: str
    contract_schema_version: str
    contract_schema_hash: str
    fixture_schema_version: str
    advertised_read_only_tools: list[str]
    controlled_outcomes: list[str]
    contracts: dict[str, Any]
