"""OpenAI Responses adapter with native function calling.

The official SDK is imported lazily inside the official client factory. Tests
inject a scripted client and do not require the optional ``[live]`` extra.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from agent_coach.core.contracts import (
    AgentStep,
    PlannerCallResult,
    PlannerDecision,
    PlannerRouting,
    ToolResult,
    ToolSpec,
)
from agent_coach.core.ports import Message
from agent_coach.core.security import compact_tool_result
from agent_coach.provider.config import (
    PLANNER_ROLE,
    SYNTHESIZER_ROLE,
    LiveProviderConfig,
)
from agent_coach.provider.errors import (
    UNKNOWN_PRICING_MESSAGE,
    LiveConfigurationError,
    ProviderAdapterError,
)
from agent_coach.provider.model_router import ModelRouter, RoutedModel
from agent_coach.provider.tool_schema import (
    PROVIDER_TOOL_CHOICE_AUTO,
    tool_specs_to_openai_tools,
)

PLANNER_INSTRUCTIONS = (
    "Select at most one declared tool when evidence is needed. "
    "Do not invent tools. Do not include secrets. "
    "When a tool result is already available, do not call another tool."
)
SYNTHESIZER_INSTRUCTIONS = (
    "Answer only from the provided grounded context. Cite source labels. "
    "If evidence is insufficient, abstain. Do not reveal secrets or raw tool JSON."
)
MAX_TOOL_OUTPUT_CHARS = 2400
MAX_GROUNDED_CONTEXT_CHARS = 2400
MAX_REPLAY_ITEMS = 16
MAX_REPLAY_TEXT_CHARS = 8192
MAX_REPLAY_TOTAL_TEXT_CHARS = MAX_REPLAY_TEXT_CHARS * 4
MAX_REPLAY_NODES = 512
MAX_REPLAY_DEPTH = 32
MIN_OUTPUT_TEXT_CHARS = 512
OUTPUT_CHARS_PER_TOKEN = 16
REASONING_ENCRYPTED_CONTENT_INCLUDE = "reasoning.encrypted_content"
SUPPORTED_RESPONSE_OUTPUT_TYPES = frozenset({"message", "reasoning", "function_call"})
SUPPORTED_MESSAGE_PHASES = frozenset({"commentary", "final_answer"})
REPLAY_ITEM_FIELDS = (
    "id",
    "status",
    "phase",
    "role",
    "content",
    "summary",
    "encrypted_content",
    "call_id",
    "name",
    "arguments",
)
REPLAY_OBJECT_FIELDS = (
    "id",
    "type",
    "status",
    "phase",
    "role",
    "content",
    "summary",
    "encrypted_content",
    "call_id",
    "name",
    "arguments",
    "text",
    "annotations",
    "refusal",
)
_UNSAFE_STATUS_TOKEN_PATTERN = re.compile(
    r"(api[_-]?key|bearer|password|secret|token|sk-[A-Za-z0-9])",
    re.IGNORECASE,
)
_TRANSPORT_CATEGORIES = {
    "APITimeoutError": "timeout",
    "TimeoutError": "timeout",
    "Timeout": "timeout",
    "RateLimitError": "rate_limit",
    "AuthenticationError": "configuration",
    "PermissionDeniedError": "configuration",
    "NotFoundError": "unsupported",
    "UnprocessableEntityError": "unsupported",
    "BadRequestError": "unsupported",
    "APIConnectionError": "dependency",
    "APIStatusError": "dependency",
    "APIError": "dependency",
    "InternalServerError": "dependency",
}


@dataclass(frozen=True)
class NormalizedFunctionCall:
    """One provider-native function call after local normalization."""

    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class NormalizedResponse:
    """Bounded provider response. Raw SDK payloads are not retained."""

    response_id: str
    status: str | None = None
    output_text: str = ""
    function_calls: tuple[NormalizedFunctionCall, ...] = ()
    output_items: tuple[dict[str, object], ...] = ()
    error: str | None = None
    incomplete_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ReplayValidationBudget:
    """Shared replay walker limits for one provider response output."""

    nodes: int = 0
    text_chars: int = 0
    active_ids: set[int] | None = None

    def add_node(self, *, path: str, depth: int) -> None:
        if depth > MAX_REPLAY_DEPTH:
            raise ProviderAdapterError(
                "dependency",
                f"dependency: provider replay nesting too deep ({path})",
            )
        self.nodes += 1
        if self.nodes > MAX_REPLAY_NODES:
            raise ProviderAdapterError(
                "dependency",
                f"dependency: provider replay object too large ({path})",
            )

    def add_text(self, length: int, *, path: str) -> None:
        self.text_chars += length
        if self.text_chars > MAX_REPLAY_TOTAL_TEXT_CHARS:
            raise ProviderAdapterError(
                "dependency",
                f"dependency: provider replay text too large ({path})",
            )

    def enter(self, value: object, *, path: str) -> int:
        object_id = id(value)
        if self.active_ids is None:
            self.active_ids = set()
        if object_id in self.active_ids:
            raise ProviderAdapterError(
                "dependency",
                f"dependency: provider replay cycle detected ({path})",
            )
        self.active_ids.add(object_id)
        return object_id

    def leave(self, object_id: int) -> None:
        if self.active_ids is not None:
            self.active_ids.discard(object_id)


@dataclass(frozen=True)
class ProviderRequest:
    """Exact payload sent to a Responses client. No credentials."""

    model_id: str
    model_role: str
    instructions: str
    input_items: tuple[dict[str, object], ...]
    tools: tuple[dict[str, object], ...] | None = None
    tool_choice: str | None = None
    parallel_tool_calls: bool | None = None
    max_output_tokens: int = 400
    previous_response_id: str | None = None
    store: bool = False
    include: tuple[str, ...] = (REASONING_ENCRYPTED_CONTENT_INCLUDE,)

    def as_sdk_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.model_id,
            "instructions": self.instructions,
            "input": [dict(item) for item in self.input_items],
            "max_output_tokens": self.max_output_tokens,
            "store": self.store,
        }
        if not self.store and self.include:
            kwargs["include"] = list(self.include)
        if self.tools is not None:
            kwargs["tools"] = [dict(tool) for tool in self.tools]
            kwargs["tool_choice"] = self.tool_choice or PROVIDER_TOOL_CHOICE_AUTO
            kwargs["parallel_tool_calls"] = False
        if self.previous_response_id and self.store:
            kwargs["previous_response_id"] = self.previous_response_id
        return kwargs


class ResponsesClientPort(Protocol):
    """Minimal Responses create boundary used by the planner adapter."""

    def create_response(self, request: ProviderRequest) -> NormalizedResponse:
        """Execute one Responses API call or raise ProviderAdapterError."""


class ScriptedResponsesClient:
    """Deterministic fake client for offline native-calling tests."""

    def __init__(
        self, script: Sequence[NormalizedResponse | BaseException]
    ) -> None:
        self.calls: list[ProviderRequest] = []
        self._script = list(script)

    def create_response(self, request: ProviderRequest) -> NormalizedResponse:
        self.calls.append(request)
        if not self._script:
            raise ProviderAdapterError(
                "dependency",
                "dependency: scripted provider responses exhausted",
            )
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            if isinstance(item, ProviderAdapterError):
                raise item
            raise _classify_transport_error(item)
        return item


class OpenAISdkResponsesClient:
    """Thin wrapper around the official OpenAI Python SDK Responses API."""

    def __init__(self, sdk_client: object) -> None:
        self._sdk_client = sdk_client

    def create_response(self, request: ProviderRequest) -> NormalizedResponse:
        responses = getattr(self._sdk_client, "responses", None)
        create = getattr(responses, "create", None)
        if not callable(create):
            raise ProviderAdapterError(
                "unsupported",
                "unsupported: OpenAI client has no responses.create",
            )
        try:
            raw = create(**request.as_sdk_kwargs())
        except ProviderAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK failures are classified
            raise _classify_transport_error(exc) from None
        return normalize_response(raw)


class OpenAIResponsesPlanner:
    """PlannerPort backed by native Responses function calling and model routing."""

    def __init__(
        self,
        config: LiveProviderConfig,
        client: ResponsesClientPort,
        *,
        router: ModelRouter | None = None,
    ) -> None:
        if config.cost_cap_usd > 0:
            raise LiveConfigurationError(
                "unknown_pricing_cost_cap",
                UNKNOWN_PRICING_MESSAGE,
            )
        self._config = config
        self._client = client
        self._router = router if router is not None else ModelRouter(config)
        self._pending_history: tuple[dict[str, object], ...] = ()
        self._pending_call_id: str | None = None
        self._pending_output: str | None = None

    def reset_run(self) -> None:
        """Drop provider-local state at the AgentRunner run boundary."""

        self._pending_history = ()
        self._pending_call_id = None
        self._pending_output = None

    def decide(
        self,
        messages: Sequence[Message],
        *,
        steps: Sequence[AgentStep],
        tools: Sequence[ToolSpec],
    ) -> PlannerCallResult:
        question = _user_question(messages)
        budget = _budget_state_text(messages)
        self._capture_tool_output(steps)
        routed = self._router.route(steps)
        if routed.role == PLANNER_ROLE:
            return self._plan(question, tools, routed, budget=budget)
        return self._synthesize(
            question, steps, routed, prior_usage=None, budget=budget
        )

    def _plan(
        self,
        question: str,
        tools: Sequence[ToolSpec],
        routed: RoutedModel,
        *,
        budget: str,
    ) -> PlannerCallResult:
        request = ProviderRequest(
            model_id=routed.model_id,
            model_role=PLANNER_ROLE,
            instructions=PLANNER_INSTRUCTIONS,
            input_items=_planner_input(
                question,
                tools,
                budget=budget,
                pending_history=self._pending_history,
                pending_call_id=self._pending_call_id,
                pending_output=self._pending_output,
            ),
            tools=tuple(tool_specs_to_openai_tools(tools)),
            tool_choice=PROVIDER_TOOL_CHOICE_AUTO,
            parallel_tool_calls=False,
            max_output_tokens=self._config.max_output_tokens,
        )
        response = self._client.create_response(request)
        _ensure_completed_response(response)
        _validate_response_output_items(response)
        _ensure_output_text_within_limit(
            response, max_output_tokens=self._config.max_output_tokens
        )
        if self._pending_output is not None:
            self._pending_history = ()
            self._pending_call_id = None
            self._pending_output = None
        usage = _usage_from(response)
        if len(response.function_calls) > 1:
            raise ProviderAdapterError(
                "multiple_tool_calls",
                "multiple_tool_calls: provider returned more than one tool call",
            )
        if len(response.function_calls) == 1:
            _require_response_id(response.response_id)
            call = response.function_calls[0]
            call_id = _require_call_id(call.call_id)
            args = _parse_tool_args(call.arguments_json)
            self._pending_history = request.input_items + _response_output_items(
                response
            )
            self._pending_call_id = call_id
            self._pending_output = None
            return PlannerCallResult(
                decision=PlannerDecision(
                    action="tool_call",
                    thought="native_function_call",
                    tool_name=call.name,
                    tool_args=args,
                    raw=None,
                ),
                token_usage=usage,
                routing=(_routing_from(routed, provider_call_id=call_id),),
            )
        answer = (response.output_text or "").strip()
        fallback = False
        if not answer:
            answer = "I cannot answer from the provided sources."
            fallback = True
        return PlannerCallResult(
            decision=PlannerDecision(
                action="final_answer",
                thought="planner_no_tool",
                final_answer=answer,
                fallback=fallback,
                raw=None,
            ),
            token_usage=usage,
            routing=(
                _routing_from(
                    routed, provider_call_id=response.response_id or None
                ),
            ),
        )

    def _synthesize(
        self,
        question: str,
        steps: Sequence[AgentStep],
        routed: RoutedModel,
        *,
        prior_usage: Mapping[str, int] | None,
        extra_routing: tuple[PlannerRouting, ...] = (),
        budget: str,
    ) -> PlannerCallResult:
        request = ProviderRequest(
            model_id=routed.model_id,
            model_role=SYNTHESIZER_ROLE,
            instructions=SYNTHESIZER_INSTRUCTIONS,
            input_items=_synthesizer_input(
                question,
                steps,
                budget=budget,
                pending_history=self._pending_history,
                pending_call_id=self._pending_call_id,
                pending_output=self._pending_output,
            ),
            tools=None,
            tool_choice=None,
            parallel_tool_calls=None,
            max_output_tokens=self._config.max_output_tokens,
        )
        response = self._client.create_response(request)
        _ensure_completed_response(response)
        _validate_response_output_items(response)
        _ensure_output_text_within_limit(
            response, max_output_tokens=self._config.max_output_tokens
        )
        self._pending_history = ()
        self._pending_call_id = None
        self._pending_output = None
        if response.function_calls:
            raise ProviderAdapterError(
                "invalid_native_call",
                "invalid_native_call: synthesizer returned a tool call",
            )
        answer = (response.output_text or "").strip()
        if not answer:
            answer = "I cannot answer from the provided sources."
        usage = _merge_usage(prior_usage, _usage_from(response))
        routing = extra_routing + (
            _routing_from(routed, provider_call_id=response.response_id or None),
        )
        return PlannerCallResult(
            decision=PlannerDecision(
                action="final_answer",
                thought="grounded_synthesis",
                final_answer=answer,
                raw=None,
            ),
            token_usage=usage,
            routing=routing,
        )

    def _capture_tool_output(self, steps: Sequence[AgentStep]) -> None:
        if self._pending_call_id is None:
            return
        for step in reversed(steps):
            if step.tool_result is None:
                continue
            compact = compact_tool_result(
                step.tool_result, max_chars=MAX_TOOL_OUTPUT_CHARS
            )
            self._pending_output = _tool_output_json(compact)
            return


def build_official_responses_client(
    config: LiveProviderConfig,
) -> OpenAISdkResponsesClient:
    """Construct the official SDK client. The SDK is an optional extra."""

    if not config.api_key.strip():
        raise LiveConfigurationError(
            "missing_api_key",
            "live profile requires AGENT_COACH_LIVE_API_KEY",
        )
    openai = _import_openai()
    client = openai.OpenAI(
        api_key=config.api_key,
        base_url=config.api_base,
        timeout=config.timeout_sec,
        max_retries=config.max_retries,
    )
    responses = getattr(client, "responses", None)
    if not callable(getattr(responses, "create", None)):
        raise LiveConfigurationError(
            "unsupported_sdk",
            "live profile requires an OpenAI SDK with Responses API support",
        )
    return OpenAISdkResponsesClient(client)


def normalize_response(raw: object) -> NormalizedResponse:
    """Project an SDK object or mapping into a bounded normalized response."""

    if isinstance(raw, NormalizedResponse):
        return raw
    if isinstance(raw, Mapping):
        return _normalize_mapping(raw)
    return _normalize_sdk_object(raw)


def _import_openai() -> Any:
    try:
        import openai
    except ImportError as exc:
        raise LiveConfigurationError(
            "missing_sdk",
            "live profile requires the optional [live] extra",
        ) from exc
    return openai


def _normalize_mapping(raw: Mapping[str, object]) -> NormalizedResponse:
    output = raw.get("output")
    output_items = tuple(_replay_items_from_output(output))
    calls = tuple(_function_calls_from_output(output_items))
    usage_raw = raw.get("usage")
    if usage_raw is None:
        usage: Mapping[str, object] = {}
    elif isinstance(usage_raw, Mapping):
        usage = usage_raw
    else:
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider usage payload malformed",
        )
    incomplete = (
        raw.get("incomplete_details")
        if isinstance(raw.get("incomplete_details"), Mapping)
        else {}
    )
    return NormalizedResponse(
        response_id=str(raw.get("id") or raw.get("response_id") or ""),
        status=str(raw["status"]) if "status" in raw else None,
        output_text=str(raw.get("output_text") or _text_from_output(output)),
        function_calls=calls,
        output_items=output_items,
        error=_provider_error_code(raw.get("error")),
        incomplete_reason=_provider_error_code(
            incomplete.get("reason") if incomplete else None
        ),
        prompt_tokens=_usage_counter_from_mapping(
            usage, primary="input_tokens", alias="prompt_tokens"
        ),
        completion_tokens=_usage_counter_from_mapping(
            usage, primary="output_tokens", alias="completion_tokens"
        ),
        total_tokens=_usage_counter_from_mapping(
            usage, primary="total_tokens", alias=None
        ),
    )


def _normalize_sdk_object(raw: object) -> NormalizedResponse:
    output = getattr(raw, "output", None)
    output_items = tuple(_replay_items_from_output(output))
    usage = getattr(raw, "usage", None)
    incomplete = getattr(raw, "incomplete_details", None)
    return NormalizedResponse(
        response_id=str(getattr(raw, "id", "") or ""),
        status=str(raw.status) if hasattr(raw, "status") else None,
        output_text=str(getattr(raw, "output_text", "") or _text_from_output(output)),
        function_calls=tuple(_function_calls_from_output(output_items)),
        output_items=output_items,
        error=_provider_error_code(getattr(raw, "error", None)),
        incomplete_reason=_provider_error_code(
            getattr(incomplete, "reason", None) if incomplete is not None else None
        ),
        prompt_tokens=_usage_counter_from_object(
            usage, primary="input_tokens", alias="prompt_tokens"
        ),
        completion_tokens=_usage_counter_from_object(
            usage, primary="output_tokens", alias="completion_tokens"
        ),
        total_tokens=_usage_counter_from_object(
            usage, primary="total_tokens", alias=None
        ),
    )


def _function_calls_from_output(
    output: object,
) -> list[NormalizedFunctionCall]:
    if not isinstance(output, Sequence) or isinstance(output, str | bytes):
        return []
    calls: list[NormalizedFunctionCall] = []
    for item in output:
        item_type = str(_item_field(item, "type") or "")
        if item_type == "custom_tool_call":
            raise ProviderAdapterError(
                "unsupported",
                "unsupported: provider returned a non-function tool",
            )
        if item_type and item_type not in SUPPORTED_RESPONSE_OUTPUT_TYPES:
            raise ProviderAdapterError(
                "unsupported",
                "unsupported: provider returned unsupported response output",
            )
        if item_type != "function_call":
            continue
        name = str(_item_field(item, "name") or "")
        arguments = _item_field(item, "arguments")
        if isinstance(arguments, Mapping):
            arguments_json = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        else:
            arguments_json = str(arguments or "")
        calls.append(
            NormalizedFunctionCall(
                call_id=str(
                    _item_field(item, "call_id") or _item_field(item, "id") or ""
                ),
                name=name,
                arguments_json=arguments_json,
            )
        )
    return calls


def _replay_items_from_output(output: object) -> list[dict[str, object]]:
    if not isinstance(output, Sequence) or isinstance(output, str | bytes):
        return []
    if len(output) > MAX_REPLAY_ITEMS:
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider response output exceeded replay limit",
        )
    items: list[dict[str, object]] = []
    budget = ReplayValidationBudget()
    for item in output:
        normalized = _normalize_replay_item(item, budget=budget)
        if normalized:
            items.append(normalized)
    return items


def _normalize_replay_item(
    item: object,
    *,
    budget: ReplayValidationBudget,
) -> dict[str, object]:
    if isinstance(item, Mapping):
        raw = item
    else:
        raw = {
            name: getattr(item, name)
            for name in (
                "id",
                "type",
                "status",
                "phase",
                "role",
                "content",
                "summary",
                "encrypted_content",
                "call_id",
                "name",
                "arguments",
            )
            if getattr(item, name, None) is not None
        }
    item_type = str(raw.get("type") or "")
    if not item_type:
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider response output item missing type",
        )
    if item_type not in SUPPORTED_RESPONSE_OUTPUT_TYPES:
        raise ProviderAdapterError(
            "unsupported",
            "unsupported: provider returned unsupported response output",
        )
    _validate_replay_item_schema(raw, item_type=item_type)
    return _normalize_replay_mapping(raw, item_type=item_type, budget=budget)


def _normalize_replay_mapping(
    raw: Mapping[str, object],
    *,
    item_type: str,
    budget: ReplayValidationBudget,
) -> dict[str, object]:
    replay: dict[str, object] = {"type": item_type}
    for key in REPLAY_ITEM_FIELDS:
        if key in raw:
            if key == "phase":
                phase = _validated_replay_phase(raw, item_type=item_type)
                replay[key] = _validated_replay_value(
                    phase,
                    path=key,
                    budget=budget,
                )
            else:
                replay[key] = _validated_replay_value(
                    raw[key],
                    path=key,
                    budget=budget,
                )
    return replay


def _validate_replay_item_schema(
    item: Mapping[str, object],
    *,
    item_type: str,
) -> None:
    if item_type == "message":
        _validate_message_replay_item(item)
    elif item_type == "function_call":
        _validate_function_call_replay_item(item)
    elif item_type == "reasoning":
        _validate_reasoning_replay_item(item)
    if "phase" in item:
        _validated_replay_phase(item, item_type=item_type)


def _validate_message_replay_item(item: Mapping[str, object]) -> None:
    role = _required_replay_string(item, "role", item_type="message")
    if role != "assistant":
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider message replay role malformed",
        )
    content = item.get("content")
    if (
        not isinstance(content, Sequence)
        or isinstance(content, str | bytes)
        or not content
    ):
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider message replay content malformed",
        )
    for block in content:
        block_type = str(_item_field(block, "type") or "")
        if block_type == "output_text":
            if not isinstance(_item_field(block, "text"), str):
                raise ProviderAdapterError(
                    "dependency",
                    "dependency: provider message replay content malformed",
                )
            continue
        if block_type == "refusal":
            if not isinstance(_item_field(block, "refusal"), str):
                raise ProviderAdapterError(
                    "dependency",
                    "dependency: provider message replay content malformed",
                )
            continue
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider message replay content malformed",
        )


def _validate_function_call_replay_item(item: Mapping[str, object]) -> None:
    _required_replay_string(item, "call_id", item_type="function_call")
    _required_replay_string(item, "name", item_type="function_call")
    _required_replay_string(item, "arguments", item_type="function_call")


def _validate_reasoning_replay_item(item: Mapping[str, object]) -> None:
    _required_replay_string(item, "id", item_type="reasoning")
    encrypted_content = item.get("encrypted_content")
    if not isinstance(encrypted_content, str) or not encrypted_content.strip():
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider reasoning item missing encrypted content",
        )


def _required_replay_string(
    item: Mapping[str, object],
    key: str,
    *,
    item_type: str,
) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProviderAdapterError(
            "dependency",
            f"dependency: provider {item_type} replay item missing {key}",
        )
    return value


def _validated_replay_phase(
    raw: Mapping[str, object],
    *,
    item_type: str,
) -> str:
    if item_type != "message":
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider replay phase is only valid on assistant messages",
        )
    if str(raw.get("role") or "") != "assistant":
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider replay phase is only valid on assistant messages",
        )
    phase = raw.get("phase")
    if not isinstance(phase, str) or phase not in SUPPORTED_MESSAGE_PHASES:
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider replay phase value malformed",
        )
    return phase


def _validated_replay_value(
    value: object,
    *,
    path: str,
    budget: ReplayValidationBudget,
    depth: int = 0,
) -> object:
    budget.add_node(path=path, depth=depth)
    if isinstance(value, str):
        if len(value) > MAX_REPLAY_TEXT_CHARS:
            raise ProviderAdapterError(
                "dependency",
                f"dependency: provider replay field too large ({path})",
            )
        budget.add_text(len(value), path=path)
        return value
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, Mapping):
        object_id = budget.enter(value, path=path)
        if len(value) > MAX_REPLAY_ITEMS:
            raise ProviderAdapterError(
                "dependency",
                f"dependency: provider replay object too large ({path})",
            )
        try:
            normalized: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ProviderAdapterError(
                        "dependency",
                        f"dependency: provider replay mapping key malformed ({path})",
                    )
                budget.add_node(path=f"{path}.key", depth=depth + 1)
                if len(key) > MAX_REPLAY_TEXT_CHARS:
                    raise ProviderAdapterError(
                        "dependency",
                        f"dependency: provider replay mapping key too large ({path})",
                    )
                budget.add_text(len(key), path=f"{path}.key")
                if key in normalized:
                    raise ProviderAdapterError(
                        "dependency",
                        f"dependency: provider replay mapping key duplicated ({path})",
                    )
                normalized[key] = _validated_replay_value(
                    item,
                    path=f"{path}.field",
                    budget=budget,
                    depth=depth + 1,
                )
            return normalized
        finally:
            budget.leave(object_id)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        object_id = budget.enter(value, path=path)
        if len(value) > MAX_REPLAY_ITEMS:
            raise ProviderAdapterError(
                "dependency",
                f"dependency: provider replay array too large ({path})",
            )
        try:
            return [
                _validated_replay_value(
                    item,
                    path=f"{path}[]",
                    budget=budget,
                    depth=depth + 1,
                )
                for item in value
            ]
        finally:
            budget.leave(object_id)
    projected = _project_replay_object(value)
    if projected:
        object_id = budget.enter(value, path=path)
        try:
            return {
                key: _validated_replay_value(
                    item,
                    path=f"{path}.field",
                    budget=budget,
                    depth=depth + 1,
                )
                for key, item in projected.items()
            }
        finally:
            budget.leave(object_id)
    text = str(value)
    if len(text) > MAX_REPLAY_TEXT_CHARS:
        raise ProviderAdapterError(
            "dependency",
            f"dependency: provider replay value too large ({path})",
        )
    budget.add_text(len(text), path=path)
    return text


def _project_replay_object(value: object) -> dict[str, object]:
    return {
        name: getattr(value, name)
        for name in REPLAY_OBJECT_FIELDS
        if getattr(value, name, None) is not None
    }


def _text_from_output(output: object) -> str:
    if isinstance(output, str):
        return output
    if not isinstance(output, Sequence) or isinstance(output, str | bytes):
        return ""
    parts: list[str] = []
    for item in output:
        if _item_field(item, "type") != "message":
            continue
        content = _item_field(item, "content")
        if isinstance(content, str):
            parts.append(content)
            continue
        if not isinstance(content, Sequence) or isinstance(content, str | bytes):
            continue
        for block in content:
            text = _item_field(block, "text")
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def _item_field(item: object, name: str) -> object:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _planner_input(
    question: str,
    tools: Sequence[ToolSpec],
    *,
    budget: str,
    pending_history: Sequence[dict[str, object]],
    pending_call_id: str | None,
    pending_output: str | None,
) -> tuple[dict[str, object], ...]:
    names = ", ".join(tool.name for tool in tools)
    items: list[dict[str, object]] = list(_continuation_items(
        pending_history, pending_call_id, pending_output
    ))
    if items:
        items.append({"role": "user", "content": budget})
        items.append(
            {
                "role": "user",
                "content": (
                    f"Available tools: {names}. "
                    "Choose at most one sequential tool call."
                ),
            }
        )
        return tuple(items)
    items.append({"role": "user", "content": question})
    items.append({"role": "user", "content": budget})
    items.append(
        {
            "role": "user",
            "content": (
                f"Available tools: {names}. "
                "Choose at most one sequential tool call."
            ),
        }
    )
    return tuple(items)


def _synthesizer_input(
    question: str,
    steps: Sequence[AgentStep],
    *,
    budget: str,
    pending_history: Sequence[dict[str, object]],
    pending_call_id: str | None,
    pending_output: str | None,
) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = list(_continuation_items(
        pending_history, pending_call_id, pending_output
    ))
    if items:
        items.append({"role": "user", "content": budget})
        items.append({"role": "user", "content": _grounded_context(steps)})
        return tuple(items)
    items.append({"role": "user", "content": question})
    items.append({"role": "user", "content": budget})
    items.append({"role": "user", "content": _grounded_context(steps)})
    return tuple(items)


def _continuation_items(
    pending_history: Sequence[dict[str, object]],
    pending_call_id: str | None,
    pending_output: str | None,
) -> tuple[dict[str, object], ...]:
    if not pending_history or pending_call_id is None or pending_output is None:
        return ()
    return (
        tuple(dict(item) for item in pending_history)
        + (
            {
                "type": "function_call_output",
                "call_id": pending_call_id,
                "output": pending_output,
            },
        )
    )


def _response_output_items(
    response: NormalizedResponse,
) -> tuple[dict[str, object], ...]:
    if response.output_items:
        items = tuple(dict(item) for item in response.output_items)
    else:
        items = tuple(
        {
            "type": "function_call",
            "call_id": call.call_id,
            "name": call.name,
            "arguments": call.arguments_json,
        }
        for call in response.function_calls
        )
    return _validate_replay_items(items, response.function_calls)


def _validate_response_output_items(response: NormalizedResponse) -> None:
    if response.output_items:
        _validate_replay_items(response.output_items, response.function_calls)


def _validate_replay_items(
    items: Sequence[dict[str, object]],
    function_calls: Sequence[NormalizedFunctionCall],
) -> tuple[dict[str, object], ...]:
    if len(items) > MAX_REPLAY_ITEMS:
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider response output exceeded replay limit",
        )
    normalized_items: list[dict[str, object]] = []
    budget = ReplayValidationBudget()
    for item in items:
        if not isinstance(item, Mapping):
            raise ProviderAdapterError(
                "dependency",
                "dependency: provider response output item malformed",
            )
        item_type = str(item.get("type") or "")
        if not item_type:
            raise ProviderAdapterError(
                "dependency",
                "dependency: provider response output item missing type",
            )
        if item_type not in SUPPORTED_RESPONSE_OUTPUT_TYPES:
            raise ProviderAdapterError(
                "unsupported",
                "unsupported: provider returned unsupported response output",
            )
        _validate_replay_item_schema(item, item_type=item_type)
        normalized_items.append(
            _normalize_replay_mapping(item, item_type=item_type, budget=budget)
        )
    normalized = tuple(normalized_items)
    _validate_replay_function_call_linkage(normalized, function_calls)
    return normalized


def _validate_replay_function_call_linkage(
    items: Sequence[dict[str, object]],
    function_calls: Sequence[NormalizedFunctionCall],
) -> None:
    replay_calls = [item for item in items if item.get("type") == "function_call"]
    if len(replay_calls) != len(function_calls):
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider function call replay mismatch",
        )
    expected_by_call_id: dict[str, NormalizedFunctionCall] = {}
    for call in function_calls:
        if call.call_id in expected_by_call_id:
            raise ProviderAdapterError(
                "dependency",
                "dependency: provider function call replay mismatch",
            )
        expected_by_call_id[call.call_id] = call
    seen_call_ids: set[str] = set()
    for item in replay_calls:
        call_id = str(item.get("call_id") or "")
        if call_id in seen_call_ids:
            raise ProviderAdapterError(
                "dependency",
                "dependency: provider function call replay mismatch",
            )
        seen_call_ids.add(call_id)
        expected = expected_by_call_id.get(call_id)
        if expected is None:
            raise ProviderAdapterError(
                "dependency",
                "dependency: provider function call replay mismatch",
            )
        if (
            item.get("name") != expected.name
            or item.get("arguments") != expected.arguments_json
        ):
            raise ProviderAdapterError(
                "dependency",
                "dependency: provider function call replay mismatch",
            )


def _grounded_context(steps: Sequence[AgentStep]) -> str:
    lines = ["Grounded context:"]
    for step in steps:
        if step.tool_result is None:
            continue
        compact = compact_tool_result(step.tool_result, max_chars=800)
        lines.append(_tool_output_json(compact))
    text = "\n".join(lines)
    if len(text) > MAX_GROUNDED_CONTEXT_CHARS:
        return text[: MAX_GROUNDED_CONTEXT_CHARS - 3] + "..."
    return text


def _tool_output_json(result: ToolResult) -> str:
    payload = {
        "ok": result.ok,
        "error": result.error,
        "data": result.data,
        "sources": result.meta.get("sources"),
        "excerpt": result.meta.get("excerpt"),
        "has_evidence": result.meta.get("has_evidence"),
    }
    text = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        return text[: MAX_TOOL_OUTPUT_CHARS - 3] + "..."
    return text


def _parse_tool_args(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        raise ProviderAdapterError(
            "invalid_native_call",
            "invalid_native_call: function arguments were empty",
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderAdapterError(
            "invalid_native_call",
            "invalid_native_call: function arguments were not valid JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise ProviderAdapterError(
            "invalid_native_call",
            "invalid_native_call: function arguments must be an object",
        )
    return parsed


def _require_call_id(call_id: str) -> str:
    normalized = call_id.strip()
    if not normalized:
        raise ProviderAdapterError(
            "invalid_native_call",
            "invalid_native_call: function call is missing call_id",
        )
    return normalized


def _require_response_id(response_id: str) -> str:
    normalized = response_id.strip()
    if not normalized:
        raise ProviderAdapterError(
            "invalid_native_call",
            "invalid_native_call: function call response is missing response_id",
        )
    return normalized


def _ensure_completed_response(response: NormalizedResponse) -> None:
    if response.status is None:
        raise ProviderAdapterError(
            "dependency",
            "dependency: provider response status missing",
        )
    status = response.status.strip().casefold()
    if status == "completed":
        return
    if status == "incomplete":
        reason = _safe_status_reason(response.incomplete_reason)
        raise ProviderAdapterError(
            "dependency",
            f"dependency: provider response incomplete ({reason})",
        )
    if status == "failed":
        reason = _safe_status_reason(response.error)
        raise ProviderAdapterError(
            "dependency",
            f"dependency: provider response failed ({reason})",
        )
    raise ProviderAdapterError(
        "dependency",
        "dependency: provider response status unsupported",
    )


def _ensure_output_text_within_limit(
    response: NormalizedResponse, *, max_output_tokens: int
) -> None:
    if len(response.output_text or "") <= _local_output_text_limit(
        max_output_tokens
    ):
        return
    raise ProviderAdapterError(
        "dependency",
        "dependency: provider output text exceeded local limit",
    )


def _local_output_text_limit(max_output_tokens: int) -> int:
    token_limit = (
        max_output_tokens
        if isinstance(max_output_tokens, int)
        and not isinstance(max_output_tokens, bool)
        else 0
    )
    return max(MIN_OUTPUT_TEXT_CHARS, token_limit * OUTPUT_CHARS_PER_TOKEN)


def _safe_status_reason(value: str | None) -> str:
    if not value:
        return "unknown"
    if _UNSAFE_STATUS_TOKEN_PATTERN.search(value):
        return "redacted"
    normalized = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_"
        for char in value.strip()
    )
    return normalized[:80] or "unknown"


def _provider_error_code(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("code", "type", "reason"):
            item = value.get(key)
            if item:
                return _safe_status_reason(str(item))
        return "provider_error"
    code = getattr(value, "code", None) or getattr(value, "type", None)
    if code:
        return _safe_status_reason(str(code))
    return _safe_status_reason(str(value))


def _budget_state_text(messages: Sequence[Message]) -> str:
    for message in reversed(messages):
        if message.get("role") != "runtime_budget":
            continue
        payload = {
            key: message.get(key)
            for key in (
                "remaining_steps",
                "max_steps",
                "elapsed_sec",
                "remaining_time_sec",
                "max_time_sec",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "remaining_tokens",
                "max_tokens",
                "total_cost_usd",
                "remaining_cost_usd",
                "max_cost_usd",
            )
        }
        return "Budget state: " + json.dumps(
            payload, ensure_ascii=False, sort_keys=True
        )
    return "Budget state: unavailable."


def _budget_after_usage(budget: str, usage: Mapping[str, int]) -> str:
    prefix = "Budget state: "
    if not budget.startswith(prefix):
        return budget
    try:
        payload = json.loads(budget.removeprefix(prefix))
    except json.JSONDecodeError:
        return budget
    if not isinstance(payload, dict):
        return budget
    prompt = int(payload.get("prompt_tokens") or 0) + int(
        usage.get("prompt_tokens") or 0
    )
    completion = int(payload.get("completion_tokens") or 0) + int(
        usage.get("completion_tokens") or 0
    )
    total = int(payload.get("total_tokens") or 0) + int(
        usage.get("total_tokens") or 0
    )
    payload["prompt_tokens"] = prompt
    payload["completion_tokens"] = completion
    total = max(total, prompt + completion)
    payload["total_tokens"] = total
    max_tokens = int(payload.get("max_tokens") or 0)
    if max_tokens > 0:
        payload["remaining_tokens"] = max(max_tokens - total, 0)
    return prefix + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _routing_from(
    routed: RoutedModel, *, provider_call_id: str | None
) -> PlannerRouting:
    return PlannerRouting(
        model_role=str(routed.role),
        model_id=str(routed.model_id),
        backend=str(routed.backend),
        routing_status=str(routed.routing_status),
        provider_call_id=provider_call_id,
    )


def _usage_from(response: NormalizedResponse) -> dict[str, int]:
    prompt = _nonnegative_int(response.prompt_tokens)
    completion = _nonnegative_int(response.completion_tokens)
    reported_total = _nonnegative_int(response.total_tokens)
    total = max(reported_total, prompt + completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _merge_usage(
    first: Mapping[str, int] | None, second: Mapping[str, int]
) -> dict[str, int]:
    if first is None:
        return dict(second)
    prompt = int(first.get("prompt_tokens") or 0) + int(
        second.get("prompt_tokens") or 0
    )
    completion = int(first.get("completion_tokens") or 0) + int(
        second.get("completion_tokens") or 0
    )
    total = int(first.get("total_tokens") or 0) + int(
        second.get("total_tokens") or 0
    )
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": max(total, prompt + completion),
    }


def _nonnegative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ProviderAdapterError(
        "dependency",
        "dependency: provider usage counter malformed",
    )


def _usage_counter_from_mapping(
    usage: Mapping[str, object], *, primary: str, alias: str | None
) -> int:
    if primary in usage:
        return _nonnegative_int(usage[primary])
    if alias is not None and alias in usage:
        return _nonnegative_int(usage[alias])
    return 0


def _usage_counter_from_object(
    usage: object, *, primary: str, alias: str | None
) -> int:
    if usage is None:
        return 0
    if hasattr(usage, primary):
        return _nonnegative_int(getattr(usage, primary))
    if alias is not None and hasattr(usage, alias):
        return _nonnegative_int(getattr(usage, alias))
    return 0


def _user_question(messages: Sequence[Message]) -> str:
    for message in messages:
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _classify_transport_error(exc: BaseException) -> ProviderAdapterError:
    name = type(exc).__name__
    category = _TRANSPORT_CATEGORIES.get(name, "dependency")
    return ProviderAdapterError(category, f"{category}: provider call failed")
