from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_coach.core.contracts import (
    AgentState,
    AgentStep,
    RunLimits,
    RunRequest,
    ToolAccess,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from agent_coach.core.runner import AgentRunner
from agent_coach.core.security import DefaultSecurityPolicy
from agent_coach.provider.config import LiveProviderConfig, ModelRoleSettings
from agent_coach.provider.errors import LiveConfigurationError, ProviderAdapterError
from agent_coach.provider.model_router import PLANNER_ROLE, SYNTHESIZER_ROLE
from agent_coach.provider.openai_responses import (
    NormalizedFunctionCall,
    NormalizedResponse,
    OpenAIResponsesPlanner,
    OpenAISdkResponsesClient,
    ProviderRequest,
    ScriptedResponsesClient,
    build_official_responses_client,
    normalize_response,
)
from agent_coach.provider.tool_schema import tool_specs_to_openai_tools

PLANNER_MODEL = "diploma-planner-model"
SYNTHESIZER_MODEL = "diploma-synthesizer-model"
LIVE_KEY = "qk"


def _config(**overrides: object) -> LiveProviderConfig:
    values = {
        "api_key": LIVE_KEY,
        "planner": ModelRoleSettings(role=PLANNER_ROLE, model_id=PLANNER_MODEL),
        "synthesizer": ModelRoleSettings(
            role=SYNTHESIZER_ROLE, model_id=SYNTHESIZER_MODEL
        ),
    }
    values.update(overrides)
    return LiveProviderConfig(**values)


def _search_tool() -> ToolSpec:
    return ToolSpec(
        name="rag.search",
        description="Semantic search over the indexed knowledge base.",
        when_to_use="Use when you need source excerpts.",
        args_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 4},
            },
            "required": ["query"],
        },
        access=ToolAccess.READ,
    )


def _profile_tool() -> ToolSpec:
    return ToolSpec(
        name="learner.get_profile",
        description="Return a public demo learner profile.",
        when_to_use="Use at the start of a study session.",
        args_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
        access=ToolAccess.READ,
    )


def _tool_call(
    name: str,
    args: dict[str, object],
    *,
    call_id: str = "call_1",
    response_id: str = "resp_plan",
    prompt_tokens: int = 4,
    completion_tokens: int = 2,
    total_tokens: int | None = None,
) -> NormalizedResponse:
    return NormalizedResponse(
        response_id=response_id,
        status="completed",
        function_calls=(
            NormalizedFunctionCall(
                call_id=call_id,
                name=name,
                arguments_json=json.dumps(args, ensure_ascii=False),
            ),
        ),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=(
            prompt_tokens + completion_tokens
            if total_tokens is None
            else total_tokens
        ),
    )


def _text(
    text: str,
    *,
    response_id: str = "resp_synth",
    prompt_tokens: int = 5,
    completion_tokens: int = 7,
    total_tokens: int | None = None,
) -> NormalizedResponse:
    return NormalizedResponse(
        response_id=response_id,
        status="completed",
        output_text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=(
            prompt_tokens + completion_tokens
            if total_tokens is None
            else total_tokens
        ),
    )


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute(
        self,
        tool: ToolSpec,
        args: dict[str, object],
        context: ToolContext,
    ) -> ToolResult:
        del context
        self.calls.append((tool.name, dict(args)))
        if tool.name == "rag.search":
            return ToolResult.success(
                {"chunks": [{"text": "Chlorophyll captures light energy."}]},
                sources=[{"file_name": "photosynthesis.md", "cite_index": 1}],
                excerpt="Chlorophyll captures light energy.",
                has_evidence=True,
            )
        if tool.name == "learner.get_profile":
            return ToolResult.success(
                {"learning_goal": "Review public diploma notes"},
                sources=[],
            )
        return ToolResult.failure(f"unknown tool {tool.name}")


def test_tool_schemas_are_sent_in_provider_function_shape() -> None:
    tools = (_search_tool(), _profile_tool())
    client = ScriptedResponsesClient(
        [
            _tool_call("rag.search", {"query": "chlorophyll"}),
            _text("Chlorophyll captures light energy [1]."),
        ]
    )
    planner = OpenAIResponsesPlanner(_config(), client)
    result = planner.decide(
        [{"role": "user", "content": "How does chlorophyll capture light?"}],
        steps=[],
        tools=tools,
    )
    request = client.calls[0]
    assert request.model_id == PLANNER_MODEL
    assert request.model_role == PLANNER_ROLE
    assert request.parallel_tool_calls is False
    assert request.tool_choice == "auto"
    assert request.as_sdk_kwargs()["include"] == ["reasoning.encrypted_content"]
    schemas = tool_specs_to_openai_tools(tools)
    assert request.tools == tuple(schemas)
    assert schemas[0]["type"] == "function"
    assert schemas[0]["name"] == "rag.search"
    assert schemas[0]["parameters"]["properties"]["query"]["type"] == "string"
    assert result.decision.action == "tool_call"
    assert result.decision.tool_name == "rag.search"
    assert result.decision.tool_args == {"query": "chlorophyll"}
    assert result.routing[0].provider_call_id == "call_1"


def test_native_tool_call_and_result_share_one_call_id() -> None:
    client = ScriptedResponsesClient(
        [
            _tool_call("rag.search", {"query": "glucose"}, call_id="call_glucose"),
            _text("Glucose stores captured energy [1]."),
        ]
    )
    planner = OpenAIResponsesPlanner(_config(), client)
    tools = (_search_tool(),)
    first = planner.decide(
        [{"role": "user", "content": "How is energy stored in glucose?"}],
        steps=[],
        tools=tools,
    )
    step = AgentStep(
        step_index=0,
        state=AgentState.TOOL_CALL,
        tool_name="rag.search",
        tool_args={"query": "glucose"},
        tool_result=ToolResult.success(
            {"chunks": [{"text": "Glucose stores energy."}]},
            sources=[{"file_name": "photosynthesis.md", "cite_index": 1}],
            excerpt="Glucose stores energy.",
            has_evidence=True,
        ),
    )
    second = planner.decide(
        [{"role": "user", "content": "How is energy stored in glucose?"}],
        steps=[step],
        tools=tools,
    )
    follow_up = client.calls[1]
    assert follow_up.model_id == SYNTHESIZER_MODEL
    assert follow_up.model_role == SYNTHESIZER_ROLE
    assert follow_up.tools is None
    assert follow_up.input_items[0]["content"] == "How is energy stored in glucose?"
    output_item = follow_up.input_items[3]
    assert output_item["type"] == "function_call"
    assert output_item["call_id"] == "call_glucose"
    assert output_item["name"] == "rag.search"
    assert follow_up.input_items[4]["type"] == "function_call_output"
    assert follow_up.input_items[4]["call_id"] == "call_glucose"
    assert follow_up.previous_response_id is None
    assert first.decision.tool_name == "rag.search"
    assert second.decision.action == "final_answer"
    assert "Glucose stores captured energy [1]." in (second.decision.final_answer or "")


def test_stateless_follow_up_replays_original_input_and_response_output() -> None:
    encrypted = "x" * 5000
    raw_plan = {
        "id": "resp_reasoned_call",
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "id": "rs_1",
                "encrypted_content": encrypted,
                "summary": [{"type": "summary_text", "text": "Need retrieval."}],
            },
            {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [
                    {"type": "output_text", "text": "I'll check the grounded notes."}
                ],
            },
            {
                "type": "function_call",
                "call_id": "call_reasoned",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ],
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }
    client = ScriptedResponsesClient(
        [
            normalize_response(raw_plan),
            _text("Chlorophyll captures light [1]."),
        ]
    )
    planner = OpenAIResponsesPlanner(_config(), client)
    first = planner.decide(
        [{"role": "user", "content": "How does chlorophyll capture light?"}],
        steps=[],
        tools=(_search_tool(),),
    )
    step = AgentStep(
        step_index=0,
        state=AgentState.TOOL_CALL,
        tool_name="rag.search",
        tool_args={"query": "chlorophyll"},
        tool_result=ToolResult.success(
            {"chunks": [{"text": "Chlorophyll captures light."}]},
            sources=[{"file_name": "photosynthesis.md", "cite_index": 1}],
            excerpt="Chlorophyll captures light.",
            has_evidence=True,
        ),
    )
    planner.decide(
        [{"role": "user", "content": "How does chlorophyll capture light?"}],
        steps=[step],
        tools=(_search_tool(),),
    )
    follow_up = client.calls[1]
    types = [item.get("type") or item.get("role") for item in follow_up.input_items]
    assert types[:7] == [
        "user",
        "user",
        "user",
        "reasoning",
        "message",
        "function_call",
        "function_call_output",
    ]
    assert follow_up.input_items[0]["content"] == (
        "How does chlorophyll capture light?"
    )
    assert follow_up.input_items[3]["id"] == "rs_1"
    assert follow_up.input_items[3]["encrypted_content"] == encrypted
    assert "phase" not in follow_up.input_items[3]
    assert follow_up.input_items[4]["type"] == "message"
    assert follow_up.input_items[4]["role"] == "assistant"
    assert follow_up.input_items[4]["phase"] == "commentary"
    assert follow_up.input_items[5]["call_id"] == "call_reasoned"
    assert "phase" not in follow_up.input_items[5]
    assert follow_up.input_items[6]["call_id"] == "call_reasoned"
    assert first.routing[0].provider_call_id == "call_reasoned"


def test_two_questions_select_different_tools_from_scripted_provider() -> None:
    search_client = ScriptedResponsesClient(
        [_tool_call("rag.search", {"query": "photosynthesis chlorophyll"})]
    )
    profile_client = ScriptedResponsesClient(
        [_tool_call("learner.get_profile", {})]
    )
    tools = (_search_tool(), _profile_tool())
    search = OpenAIResponsesPlanner(_config(), search_client).decide(
        [{"role": "user", "content": "Explain photosynthesis and chlorophyll."}],
        steps=[],
        tools=tools,
    )
    profile = OpenAIResponsesPlanner(_config(), profile_client).decide(
        [{"role": "user", "content": "What is the current learner profile?"}],
        steps=[],
        tools=tools,
    )
    assert "Explain photosynthesis and chlorophyll." in str(
        search_client.calls[0].input_items
    )
    assert "What is the current learner profile?" in str(
        profile_client.calls[0].input_items
    )
    assert search.decision.tool_name == "rag.search"
    assert profile.decision.tool_name == "learner.get_profile"
    assert search.decision.tool_name != profile.decision.tool_name


def test_planner_and_synthesizer_use_distinct_configured_models() -> None:
    client = ScriptedResponsesClient(
        [
            _tool_call("rag.search", {"query": "chlorophyll"}),
            _text("Chlorophyll captures light [1]."),
        ]
    )
    planner = OpenAIResponsesPlanner(_config(), client)
    tools = (_search_tool(),)
    planner.decide(
        [{"role": "user", "content": "How does chlorophyll work?"}],
        steps=[],
        tools=tools,
    )
    step = AgentStep(
        step_index=0,
        state=AgentState.TOOL_CALL,
        tool_name="rag.search",
        tool_result=ToolResult.success({"chunks": []}, sources=[]),
    )
    planner.decide(
        [{"role": "user", "content": "How does chlorophyll work?"}],
        steps=[step],
        tools=tools,
    )
    assert client.calls[0].model_id == PLANNER_MODEL
    assert client.calls[1].model_id == SYNTHESIZER_MODEL
    assert client.calls[0].model_id != client.calls[1].model_id


def test_malformed_unknown_invalid_and_multiple_calls_fail_closed() -> None:
    tools = (_search_tool(),)
    malformed = OpenAIResponsesPlanner(
        _config(),
        ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id="resp_bad_json",
                    status="completed",
                    function_calls=(
                        NormalizedFunctionCall(
                            call_id="call_bad",
                            name="rag.search",
                            arguments_json="{not-json",
                        ),
                    ),
                )
            ]
        ),
    )
    with pytest.raises(ProviderAdapterError, match="invalid_native_call"):
        malformed.decide(
            [{"role": "user", "content": "bad json"}],
            steps=[],
            tools=tools,
        )

    missing_id = OpenAIResponsesPlanner(
        _config(),
        ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id="resp_missing_id",
                    status="completed",
                    function_calls=(
                        NormalizedFunctionCall(
                            call_id="  ",
                            name="rag.search",
                            arguments_json='{"query": "x"}',
                        ),
                    ),
                )
            ]
        ),
    )
    with pytest.raises(ProviderAdapterError, match="call_id"):
        missing_id.decide(
            [{"role": "user", "content": "missing id"}],
            steps=[],
            tools=tools,
        )

    missing_response_id = OpenAIResponsesPlanner(
        _config(),
        ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id="",
                    status="completed",
                    function_calls=(
                        NormalizedFunctionCall(
                            call_id="call_orphan",
                            name="rag.search",
                            arguments_json='{"query": "x"}',
                        ),
                    ),
                )
            ]
        ),
    )
    with pytest.raises(ProviderAdapterError, match="response_id"):
        missing_response_id.decide(
            [{"role": "user", "content": "missing response id"}],
            steps=[],
            tools=tools,
        )

    multiple = OpenAIResponsesPlanner(
        _config(),
        ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id="resp_multi",
                    status="completed",
                    function_calls=(
                        NormalizedFunctionCall(
                            call_id="call_a",
                            name="rag.search",
                            arguments_json='{"query": "a"}',
                        ),
                        NormalizedFunctionCall(
                            call_id="call_b",
                            name="learner.get_profile",
                            arguments_json="{}",
                        ),
                    ),
                )
            ]
        ),
    )
    with pytest.raises(ProviderAdapterError, match="multiple_tool_calls"):
        multiple.decide(
            [{"role": "user", "content": "two tools"}],
            steps=[],
            tools=tools,
        )

    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(
            _config(),
            ScriptedResponsesClient([_tool_call("not.a.tool", {"query": "x"})]),
        ),
        tools=tools,
        tool_executor=RecordingExecutor(),
        security_policy=DefaultSecurityPolicy(),
    )
    unknown = runner.run(RunRequest(question="unknown tool", run_id="unknown-live"))
    assert unknown.stop_reason.value == "unknown_tool"
    assert unknown.steps[0].tool_result is None

    invalid_runner = AgentRunner(
        planner=OpenAIResponsesPlanner(
            _config(),
            ScriptedResponsesClient(
                [_tool_call("rag.search", {"query": "x", "threshold": 0.1})]
            ),
        ),
        tools=tools,
        tool_executor=RecordingExecutor(),
        security_policy=DefaultSecurityPolicy(),
    )
    invalid = invalid_runner.run(
        RunRequest(question="invalid args", run_id="invalid-live")
    )
    assert invalid.stop_reason.value == "invalid_decision"
    assert invalid.steps[0].tool_result is None


def test_incomplete_and_failed_provider_responses_fail_closed() -> None:
    cases = [
        (
            NormalizedResponse(
                response_id="resp_incomplete",
                status="incomplete",
                output_text="partial",
                incomplete_reason="max_output_tokens",
            ),
            "incomplete",
        ),
        (
            NormalizedResponse(
                response_id="resp_failed",
                status="failed",
                output_text="partial",
                error="server_error",
            ),
            "failed",
        ),
    ]
    for response, marker in cases:
        planner = OpenAIResponsesPlanner(
            _config(), ScriptedResponsesClient([response])
        )
        with pytest.raises(ProviderAdapterError, match=marker):
            planner.decide(
                [{"role": "user", "content": "provider status"}],
                steps=[],
                tools=(_search_tool(),),
            )


def test_missing_unknown_and_secret_status_fail_closed_safely() -> None:
    cases = [
        NormalizedResponse(response_id="resp_missing", output_text="ok"),
        NormalizedResponse(
            response_id="resp_unknown",
            status="unexpected-secret=demo",
            output_text="ok",
        ),
    ]
    for response in cases:
        planner = OpenAIResponsesPlanner(
            _config(), ScriptedResponsesClient([response])
        )
        with pytest.raises(ProviderAdapterError) as raised:
            planner.decide(
                [{"role": "user", "content": "provider status"}],
                steps=[],
                tools=(_search_tool(),),
            )
        message = str(raised.value)
        assert "completed" not in message
        assert "unexpected-secret=demo" not in message
        assert "secret" not in message


def test_malformed_provider_usage_counters_fail_closed() -> None:
    cases = [
        {"input_tokens": -100, "output_tokens": -100, "total_tokens": 1},
        {"input_tokens": 1.5, "output_tokens": 1, "total_tokens": 2},
        {"input_tokens": True, "output_tokens": 1, "total_tokens": 2},
        {"input_tokens": "1", "output_tokens": 1, "total_tokens": 2},
    ]
    for usage in cases:
        with pytest.raises(ProviderAdapterError, match="usage counter"):
            normalize_response(
                {
                    "id": "resp_bad_usage",
                    "status": "completed",
                    "output_text": "ok",
                    "output": [],
                    "usage": usage,
                }
            )

    planner = OpenAIResponsesPlanner(
        _config(),
        ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id="resp_bad_usage",
                    status="completed",
                    output_text="ok",
                    prompt_tokens=-100,
                    completion_tokens=-100,
                    total_tokens=1,
                )
            ]
        ),
    )
    with pytest.raises(ProviderAdapterError, match="usage counter"):
        planner.decide(
            [{"role": "user", "content": "bad usage"}],
            steps=[],
            tools=(_search_tool(),),
        )


def test_unsupported_response_output_items_fail_before_tool_execution() -> None:
    executor = RecordingExecutor()
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(
            _config(),
            ScriptedResponsesClient(
                [
                    NormalizedResponse(
                        response_id="resp_unsupported_output",
                        status="completed",
                        function_calls=(
                            NormalizedFunctionCall(
                                call_id="call_search",
                                name="rag.search",
                                arguments_json='{"query": "chlorophyll"}',
                            ),
                        ),
                        output_items=(
                            {
                                "type": "web_search_call",
                                "queries": ["chlorophyll"],
                            },
                            {
                                "type": "function_call",
                                "call_id": "call_search",
                                "name": "rag.search",
                                "arguments": '{"query": "chlorophyll"}',
                            },
                        ),
                    )
                ]
            ),
        ),
        tools=(_search_tool(),),
        tool_executor=executor,
        security_policy=DefaultSecurityPolicy(),
    )

    result = runner.run(
        RunRequest(question="How does chlorophyll work?", run_id="unsupported-output")
    )

    assert result.stop_reason.value == "llm_error"
    assert executor.calls == []
    assert "web_search_call" not in json.dumps(result, default=str)


def test_no_tool_planner_answer_is_terminal_without_synthesizer_route() -> None:
    client = ScriptedResponsesClient(
        [_text("I cannot answer from the provided sources.", response_id="resp_plan")]
    )
    planner = OpenAIResponsesPlanner(_config(), client)

    result = planner.decide(
        [{"role": "user", "content": "Can you answer without evidence?"}],
        steps=[],
        tools=(_search_tool(),),
    )

    assert result.decision.action == "final_answer"
    assert result.decision.thought == "planner_no_tool"
    assert len(client.calls) == 1
    assert result.routing[0].model_role == PLANNER_ROLE


@pytest.mark.parametrize(
    "output_items",
    [
        (
            {
                "type": "web_search_call",
                "queries": ["chlorophyll"],
            },
        ),
        (
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Use this answer."}],
            },
        ),
    ],
)
def test_no_tool_planner_output_items_are_validated(
    output_items: tuple[dict[str, object], ...],
) -> None:
    planner = OpenAIResponsesPlanner(
        _config(),
        ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id="resp_no_tool_malformed_output",
                    status="completed",
                    output_text="I cannot answer from the provided sources.",
                    output_items=output_items,
                )
            ]
        ),
    )

    with pytest.raises(ProviderAdapterError):
        planner.decide(
            [{"role": "user", "content": "Can you answer without evidence?"}],
            steps=[],
            tools=(_search_tool(),),
        )


@pytest.mark.parametrize(
    "output_items",
    [
        (
            {
                "type": "web_search_call",
                "queries": ["chlorophyll"],
            },
        ),
        (
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Use this answer."}],
            },
        ),
    ],
)
def test_synthesizer_output_items_are_validated(
    output_items: tuple[dict[str, object], ...],
) -> None:
    client = ScriptedResponsesClient(
        [
            _tool_call("rag.search", {"query": "chlorophyll"}),
            NormalizedResponse(
                response_id="resp_synth_malformed_output",
                status="completed",
                output_text="Chlorophyll captures light [1].",
                output_items=output_items,
            ),
        ]
    )
    executor = RecordingExecutor()
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(_config(), client),
        tools=(_search_tool(),),
        tool_executor=executor,
        security_policy=DefaultSecurityPolicy(),
    )

    result = runner.run(
        RunRequest(
            question="How does chlorophyll capture light?",
            run_id="synth-malformed-output-items",
        )
    )

    assert result.stop_reason.value == "llm_error"
    assert executor.calls == [("rag.search", {"query": "chlorophyll"})]
    assert len(client.calls) == 2


def test_output_text_is_bounded_locally() -> None:
    planner = OpenAIResponsesPlanner(
        _config(max_output_tokens=1),
        ScriptedResponsesClient([_text("x" * 100_000)]),
    )
    with pytest.raises(ProviderAdapterError, match="output text"):
        planner.decide(
            [{"role": "user", "content": "oversized response"}],
            steps=[],
            tools=(_search_tool(),),
        )


def test_replay_limits_fail_closed_without_dropping_or_truncating_items() -> None:
    too_many_output_items = [
        {"type": "reasoning", "id": f"rs_{index}"}
        for index in range(16)
    ] + [
        {
            "type": "function_call",
            "call_id": "call_after_limit",
            "name": "rag.search",
            "arguments": '{"query": "chlorophyll"}',
        }
    ]
    with pytest.raises(ProviderAdapterError, match="replay limit"):
        normalize_response(
            {
                "id": "resp_too_many",
                "status": "completed",
                "output": too_many_output_items,
            }
        )

    too_large_encrypted = "x" * 9000
    with pytest.raises(ProviderAdapterError, match="encrypted_content"):
        normalize_response(
            {
                "id": "resp_too_large",
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_big",
                        "encrypted_content": too_large_encrypted,
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_big",
                        "name": "rag.search",
                        "arguments": '{"query": "chlorophyll"}',
                    },
                ],
            }
        )

    mismatched_replay = OpenAIResponsesPlanner(
        _config(),
        ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id="resp_mismatch",
                    status="completed",
                    function_calls=(
                        NormalizedFunctionCall(
                            call_id="call_missing",
                            name="rag.search",
                            arguments_json='{"query": "chlorophyll"}',
                        ),
                    ),
                    output_items=(
                        {
                            "type": "reasoning",
                            "id": "rs_only",
                            "encrypted_content": "opaque",
                        },
                    ),
                )
            ]
        ),
    )
    with pytest.raises(ProviderAdapterError, match="replay mismatch"):
        mismatched_replay.decide(
            [{"role": "user", "content": "missing replay call"}],
            steps=[],
            tools=(_search_tool(),),
        )


def test_direct_final_output_items_use_replay_size_limits() -> None:
    planner = OpenAIResponsesPlanner(
        _config(),
        ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id="resp_huge_direct_message",
                    status="completed",
                    output_text="I cannot answer from the provided sources.",
                    output_items=(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "x" * 100_000}
                            ],
                        },
                    ),
                )
            ]
        ),
    )

    with pytest.raises(ProviderAdapterError, match="too large"):
        planner.decide(
            [{"role": "user", "content": "Can you answer without evidence?"}],
            steps=[],
            tools=(_search_tool(),),
        )


def test_direct_tool_output_items_use_replay_size_limits_before_execution() -> None:
    executor = RecordingExecutor()
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(
            _config(),
            ScriptedResponsesClient(
                [
                    NormalizedResponse(
                        response_id="resp_huge_direct_tool_message",
                        status="completed",
                        function_calls=(
                            NormalizedFunctionCall(
                                call_id="call_huge_history",
                                name="rag.search",
                                arguments_json='{"query": "chlorophyll"}',
                            ),
                        ),
                        output_items=(
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [
                                    {"type": "output_text", "text": "x" * 100_000}
                                ],
                            },
                            {
                                "type": "function_call",
                                "call_id": "call_huge_history",
                                "name": "rag.search",
                                "arguments": '{"query": "chlorophyll"}',
                            },
                        ),
                    )
                ]
            ),
        ),
        tools=(_search_tool(),),
        tool_executor=executor,
        security_policy=DefaultSecurityPolicy(),
    )

    result = runner.run(
        RunRequest(
            question="How does chlorophyll capture light?",
            run_id="huge-direct-tool-output-items",
        )
    )

    assert result.stop_reason.value == "llm_error"
    assert executor.calls == []


def test_replay_projection_fails_closed_on_excessive_depth() -> None:
    nested: object = "leaf"
    for _ in range(1200):
        nested = [nested]

    with pytest.raises(ProviderAdapterError, match="nesting"):
        normalize_response(
            {
                "id": "resp_deep_replay",
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_deep",
                        "encrypted_content": "opaque",
                        "summary": nested,
                    },
                ],
            }
        )


def test_replay_projection_fails_closed_on_cumulative_text_budget() -> None:
    with pytest.raises(ProviderAdapterError, match="text too large"):
        normalize_response(
            {
                "id": "resp_text_budget",
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_text_budget",
                        "encrypted_content": "opaque",
                        "summary": ["x" * 8000 for _ in range(5)],
                    },
                ],
            }
        )


def test_replay_projection_bounds_mapping_keys() -> None:
    oversized_key = "k" * 100_000
    with pytest.raises(ProviderAdapterError, match="mapping key too large"):
        normalize_response(
            {
                "id": "resp_oversized_mapping_key",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Checking notes.",
                                "annotations": [{oversized_key: "value"}],
                            }
                        ],
                    }
                ],
            }
        )

    with pytest.raises(ProviderAdapterError, match="mapping key malformed"):
        normalize_response(
            {
                "id": "resp_non_string_mapping_key",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Checking notes.",
                                "annotations": [{1: "numeric", "1": "string"}],
                            }
                        ],
                    }
                ],
            }
        )


def test_replay_mapping_keys_share_cumulative_text_budget() -> None:
    annotations = [{str(index) * 8000: ""} for index in range(1, 6)]
    with pytest.raises(ProviderAdapterError, match="text too large"):
        normalize_response(
            {
                "id": "resp_mapping_key_text_budget",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Checking notes.",
                                "annotations": annotations,
                            }
                        ],
                    }
                ],
            }
        )


def test_replay_projection_fails_closed_on_sdk_object_cycles() -> None:
    block = SimpleNamespace(type="output_text", text="Checking notes.")
    block.annotations = [block]
    raw = SimpleNamespace(
        id="resp_cyclic_sdk",
        status="completed",
        output_text="",
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[block],
            )
        ],
    )

    with pytest.raises(ProviderAdapterError, match="cycle"):
        normalize_response(raw)


def test_malformed_replay_items_fail_closed() -> None:
    with pytest.raises(ProviderAdapterError, match="missing type"):
        normalize_response(
            {
                "id": "resp_missing_item_type",
                "status": "completed",
                "output": [
                    {"id": "item_without_type"},
                    {
                        "type": "function_call",
                        "call_id": "call_ok",
                        "name": "rag.search",
                        "arguments": '{"query": "chlorophyll"}',
                    },
                ],
            }
        )

    with pytest.raises(ProviderAdapterError, match="encrypted content"):
        normalize_response(
            {
                "id": "resp_reasoning_without_encrypted_content",
                "status": "completed",
                "output": [
                    {"type": "reasoning", "id": "rs_missing"},
                    {
                        "type": "function_call",
                        "call_id": "call_ok",
                        "name": "rag.search",
                        "arguments": '{"query": "chlorophyll"}',
                    },
                ],
            }
        )


@pytest.mark.parametrize(
    "output",
    [
        [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Use the tool."}],
            },
            {
                "type": "function_call",
                "call_id": "call_ok",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ],
        [
            {
                "type": "message",
                "role": "assistant",
                "content": "Checking notes.",
            },
            {
                "type": "function_call",
                "call_id": "call_ok",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ],
        [
            {
                "type": "function_call",
                "call_id": "call_ok",
                "arguments": '{"query": "chlorophyll"}',
            },
        ],
        [
            {
                "type": "function_call",
                "call_id": "call_ok",
                "name": "rag.search",
                "arguments": {"query": "chlorophyll"},
            },
        ],
        [
            {
                "type": "reasoning",
                "encrypted_content": "opaque",
            },
            {
                "type": "function_call",
                "call_id": "call_ok",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ],
    ],
)
def test_malformed_replay_item_schema_fails_closed(
    output: list[dict[str, object]],
) -> None:
    with pytest.raises(ProviderAdapterError, match="replay"):
        normalize_response(
            {
                "id": "resp_malformed_replay_schema",
                "status": "completed",
                "output": output,
            }
        )


@pytest.mark.parametrize(
    "output",
    [
        [
            {
                "type": "message",
                "role": "assistant",
                "phase": {"value": "commentary"},
                "content": [{"type": "output_text", "text": "Checking notes."}],
            },
            {
                "type": "function_call",
                "call_id": "call_ok",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ],
        [
            {
                "type": "reasoning",
                "id": "rs_wrong_phase",
                "phase": "commentary",
                "encrypted_content": "opaque",
            },
            {
                "type": "function_call",
                "call_id": "call_ok",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ],
        [
            {
                "type": "function_call",
                "phase": "commentary",
                "call_id": "call_ok",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ],
    ],
)
def test_invalid_replay_phase_fails_closed_before_tool_execution(
    output: list[dict[str, object]],
) -> None:
    with pytest.raises(ProviderAdapterError, match="phase"):
        normalize_response(
            {
                "id": "resp_invalid_phase",
                "status": "completed",
                "output": output,
            }
        )


def test_incomplete_normalized_function_call_replay_fails_before_execution() -> None:
    executor = RecordingExecutor()
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(
            _config(),
            ScriptedResponsesClient(
                [
                    NormalizedResponse(
                        response_id="resp_incomplete_normalized_replay",
                        status="completed",
                        function_calls=(
                            NormalizedFunctionCall(
                                call_id="call_missing_fields",
                                name="rag.search",
                                arguments_json='{"query": "chlorophyll"}',
                            ),
                        ),
                        output_items=(
                            {
                                "type": "function_call",
                                "call_id": "call_missing_fields",
                            },
                        ),
                    )
                ]
            ),
        ),
        tools=(_search_tool(),),
        tool_executor=executor,
        security_policy=DefaultSecurityPolicy(),
    )

    result = runner.run(
        RunRequest(
            question="How does chlorophyll capture light?",
            run_id="incomplete-normalized-replay",
        )
    )

    assert result.stop_reason.value == "llm_error"
    assert executor.calls == []


@pytest.mark.parametrize(
    "output_items",
    [
        (
            {
                "type": "function_call",
                "call_id": "call_linked",
                "name": "learner.get_profile",
                "arguments": '{"query": "chlorophyll"}',
            },
        ),
        (
            {
                "type": "function_call",
                "call_id": "call_linked",
                "name": "rag.search",
                "arguments": '{"query": "glucose"}',
            },
        ),
        (
            {
                "type": "function_call",
                "call_id": "call_linked",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
            {
                "type": "function_call",
                "call_id": "call_extra",
                "name": "learner.get_profile",
                "arguments": "{}",
            },
        ),
        (
            {
                "type": "function_call",
                "call_id": "call_linked",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
            {
                "type": "function_call",
                "call_id": "call_linked",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ),
    ],
)
def test_normalized_function_call_replay_mismatch_fails_before_execution(
    output_items: tuple[dict[str, object], ...],
) -> None:
    executor = RecordingExecutor()
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(
            _config(),
            ScriptedResponsesClient(
                [
                    NormalizedResponse(
                        response_id="resp_mismatched_normalized_replay",
                        status="completed",
                        function_calls=(
                            NormalizedFunctionCall(
                                call_id="call_linked",
                                name="rag.search",
                                arguments_json='{"query": "chlorophyll"}',
                            ),
                        ),
                        output_items=output_items,
                    )
                ]
            ),
        ),
        tools=(_search_tool(), _profile_tool()),
        tool_executor=executor,
        security_policy=DefaultSecurityPolicy(),
    )

    result = runner.run(
        RunRequest(
            question="How does chlorophyll capture light?",
            run_id="mismatched-normalized-replay",
        )
    )

    assert result.stop_reason.value == "llm_error"
    assert executor.calls == []


def test_normalized_replay_phase_fails_closed_before_tool_execution() -> None:
    response = NormalizedResponse(
        response_id="resp_invalid_normalized_phase",
        status="completed",
        function_calls=(
            NormalizedFunctionCall(
                call_id="call_invalid_phase",
                name="rag.search",
                arguments_json='{"query": "chlorophyll"}',
            ),
        ),
        output_items=(
            {
                "type": "function_call",
                "phase": "commentary",
                "call_id": "call_invalid_phase",
                "name": "rag.search",
                "arguments": '{"query": "chlorophyll"}',
            },
        ),
    )
    planner = OpenAIResponsesPlanner(_config(), ScriptedResponsesClient([response]))

    with pytest.raises(ProviderAdapterError, match="phase"):
        planner.decide(
            [{"role": "user", "content": "How does chlorophyll capture light?"}],
            steps=[],
            tools=(_search_tool(),),
        )


def test_unknown_provider_output_types_are_rejected_during_normalization() -> None:
    with pytest.raises(ProviderAdapterError, match="unsupported response output"):
        normalize_response(
            {
                "id": "resp_web_search",
                "status": "completed",
                "output": [
                    {
                        "type": "web_search_call",
                        "queries": ["chlorophyll"],
                    }
                ],
            }
        )


def test_replay_errors_do_not_expose_provider_mapping_keys() -> None:
    with pytest.raises(ProviderAdapterError) as raised:
        normalize_response(
            {
                "id": "resp_secret_key",
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_secret_key",
                        "encrypted_content": "opaque",
                        "summary": {"secret=LEAKMARK": "x" * 9000},
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_secret_key",
                        "name": "rag.search",
                        "arguments": '{"query": "chlorophyll"}',
                    },
                ],
            }
        )
    message = str(raised.value)
    assert "LEAKMARK" not in message
    assert "secret" not in message


def test_timeout_rate_limit_unsupported_and_dependency_errors_are_bounded() -> None:
    class APITimeoutError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    class BadRequestError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    cases = [
        (APITimeoutError("secret timeout body " + LIVE_KEY), "timeout"),
        (RateLimitError("secret rate body " + LIVE_KEY), "rate_limit"),
        (BadRequestError("secret unsupported body " + LIVE_KEY), "unsupported"),
        (APIConnectionError("secret dependency body " + LIVE_KEY), "dependency"),
    ]
    for exc, category in cases:
        planner = OpenAIResponsesPlanner(_config(), ScriptedResponsesClient([exc]))
        with pytest.raises(ProviderAdapterError, match=category) as raised:
            planner.decide(
                [{"role": "user", "content": "provider error"}],
                steps=[],
                tools=(_search_tool(),),
            )
        assert LIVE_KEY not in str(raised.value)
        assert "secret" not in str(raised.value)


def test_sdk_wrapper_does_not_put_credentials_on_the_wire_payload() -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {
                "id": "resp_sdk",
                "status": "completed",
                "output_text": "ok",
                "output": [],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }

    wrapper = OpenAISdkResponsesClient(SimpleNamespace(responses=FakeResponses()))
    request = ProviderRequest(
        model_id=PLANNER_MODEL,
        model_role=PLANNER_ROLE,
        instructions="test",
        input_items=({"role": "user", "content": "q"},),
        tools=tuple(tool_specs_to_openai_tools((_search_tool(),))),
        tool_choice="auto",
        parallel_tool_calls=False,
        max_output_tokens=32,
    )
    response = wrapper.create_response(request)
    assert "api_key" not in captured
    assert LIVE_KEY not in json.dumps(captured)
    assert captured["tools"][0]["type"] == "function"
    assert captured["parallel_tool_calls"] is False
    assert captured["store"] is False
    assert "previous_response_id" not in captured
    assert response.response_id == "resp_sdk"


def test_usage_from_planner_and_synthesizer_is_summed_once() -> None:
    client = ScriptedResponsesClient(
        [
            _tool_call("rag.search", {"query": "chlorophyll"}),
            _text("Chlorophyll captures light [1]."),
        ]
    )
    executor = RecordingExecutor()
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(_config(), client),
        tools=(_search_tool(),),
        tool_executor=executor,
        security_policy=DefaultSecurityPolicy(),
    )
    result = runner.run(
        RunRequest(question="How does chlorophyll capture light?", run_id="usage-live")
    )
    assert result.trace["prompt_tokens"] == 9
    assert result.trace["completion_tokens"] == 9
    assert result.trace["total_tokens"] == 18
    assert result.trace["cost_status"] == "unknown"
    assert result.trace["total_cost_usd"] is None
    roles = [item["model_role"] for item in result.trace["model_routes"]]
    assert roles == ["planner", "synthesizer"]
    assert {item["model_id"] for item in result.trace["model_routes"]} == {
        PLANNER_MODEL,
        SYNTHESIZER_MODEL,
    }
    assert executor.calls == [("rag.search", {"query": "chlorophyll"})]


def test_provider_requests_are_stateless_across_reused_runner_runs() -> None:
    client = ScriptedResponsesClient(
        [
            _tool_call("rag.search", {"query": "chlorophyll"}, response_id="resp_a"),
            _text("Chlorophyll captures light [1].", response_id="resp_b"),
            _text("I cannot answer from the provided sources.", response_id="resp_c"),
        ]
    )
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(_config(), client),
        tools=(_search_tool(),),
        tool_executor=RecordingExecutor(),
        security_policy=DefaultSecurityPolicy(),
    )
    first = runner.run(RunRequest(question="How does chlorophyll work?", run_id="r1"))
    second = runner.run(RunRequest(question="What is chlorophyll?", run_id="r2"))
    assert first.stop_reason.value == "completed"
    assert second.stop_reason.value == "completed"
    assert all(call.previous_response_id is None for call in client.calls)
    assert all(call.as_sdk_kwargs()["store"] is False for call in client.calls)
    assert "resp_b" not in str(client.calls[-1].input_items)
    assert "function_call_output" not in str(client.calls[-1].input_items)


def test_final_provider_usage_is_checked_against_hard_limits() -> None:
    client = ScriptedResponsesClient(
        [
            _text(
                "Ready for synthesis.",
                response_id="resp_plan",
                prompt_tokens=100,
                completion_tokens=100,
                total_tokens=1,
            ),
        ]
    )
    executor = RecordingExecutor()
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(_config(), client),
        tools=(_search_tool(),),
        tool_executor=executor,
        security_policy=DefaultSecurityPolicy(),
    )
    result = runner.run(
        RunRequest(
            question="How does chlorophyll work?",
            run_id="token-limit-live",
            limits=RunLimits(max_tokens=10),
        )
    )
    assert result.stop_reason.value == "max_tokens"
    assert result.trace["total_tokens"] == 200
    assert result.success is False
    assert executor.calls == []
    assert len(client.calls) == 1


def test_final_provider_call_is_checked_against_time_limit() -> None:
    class JumpClock:
        def __init__(self) -> None:
            self._values = [0.0, 0.0, 100.0, 100.0]

        def perf_counter(self) -> float:
            if len(self._values) > 1:
                return self._values.pop(0)
            return self._values[0]

    client = ScriptedResponsesClient(
        [_text("Ready for synthesis.", response_id="resp_plan")]
    )
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(_config(), client),
        tools=(_search_tool(),),
        tool_executor=RecordingExecutor(),
        security_policy=DefaultSecurityPolicy(),
        clock=JumpClock(),
    )
    result = runner.run(
        RunRequest(
            question="How does chlorophyll work?",
            run_id="time-limit-live",
            limits=RunLimits(max_time_sec=10.0),
        )
    )
    assert result.stop_reason.value == "max_time"
    assert result.trace["duration_ms"] >= 100000
    assert len(client.calls) == 1


def test_budget_state_reaches_provider_input_from_runner_limits() -> None:
    client = ScriptedResponsesClient(
        [_text("I cannot answer from the provided sources.")]
    )
    runner = AgentRunner(
        planner=OpenAIResponsesPlanner(_config(), client),
        tools=(_search_tool(),),
        tool_executor=RecordingExecutor(),
        security_policy=DefaultSecurityPolicy(),
    )
    runner.run(
        RunRequest(
            question="What can be answered?",
            run_id="budget-live",
            limits=RunLimits(max_steps=3, max_time_sec=20.0, max_tokens=99),
        )
    )
    serialized = str(client.calls[0].input_items)
    assert "Budget state:" in serialized
    assert '"remaining_steps": 2' in serialized
    assert '"max_time_sec": 20.0' in serialized
    assert '"remaining_tokens": 99' in serialized


def test_active_cost_cap_with_unknown_pricing_fails_closed() -> None:
    with pytest.raises(LiveConfigurationError, match="cloud pricing is unknown"):
        OpenAIResponsesPlanner(_config(cost_cap_usd=0.02), ScriptedResponsesClient([]))


def test_normalize_response_accepts_sdk_objects_without_retaining_raw_payload() -> None:
    raw = SimpleNamespace(
        id="resp_obj",
        status="completed",
        output_text="",
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                phase="final_answer",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        text="I can answer from the grounded notes.",
                    )
                ],
            ),
            SimpleNamespace(
                type="function_call",
                call_id="call_obj",
                name="rag.search",
                arguments='{"query": "chlorophyll"}',
            )
        ],
        usage=SimpleNamespace(input_tokens=3, output_tokens=1, total_tokens=4),
    )
    normalized = normalize_response(raw)
    assert normalized.function_calls[0].name == "rag.search"
    assert json.loads(normalized.function_calls[0].arguments_json) == {
        "query": "chlorophyll"
    }
    assert normalized.output_items[0]["role"] == "assistant"
    assert normalized.output_items[0]["phase"] == "final_answer"
    assert normalized.output_items[0]["content"] == [
        {
            "type": "output_text",
            "text": "I can answer from the grounded notes.",
        }
    ]
    dumped = json.dumps(normalized, default=str)
    assert "SimpleNamespace" not in dumped


def test_build_official_client_without_sdk_is_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing() -> None:
        raise LiveConfigurationError(
            "missing_sdk",
            "live profile requires the optional [live] extra",
        )

    monkeypatch.setattr(
        "agent_coach.provider.openai_responses._import_openai",
        _missing,
    )
    with pytest.raises(LiveConfigurationError, match="optional"):
        build_official_responses_client(_config())


def test_build_official_client_requires_responses_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_sdk = SimpleNamespace(OpenAI=lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        "agent_coach.provider.openai_responses._import_openai",
        lambda: legacy_sdk,
    )

    with pytest.raises(LiveConfigurationError, match="Responses API") as raised:
        build_official_responses_client(_config())

    assert raised.value.code == "unsupported_sdk"
    assert LIVE_KEY not in str(raised.value)
