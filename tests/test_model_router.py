from __future__ import annotations

from agent_coach.core.contracts import AgentState, AgentStep, ToolResult
from agent_coach.provider.config import (
    ROUTING_DEGRADED,
    ROUTING_DISTINCT,
    LiveProviderConfig,
    ModelRoleSettings,
)
from agent_coach.provider.model_router import (
    PLANNER_ROLE,
    SYNTHESIZER_ROLE,
    ModelRouter,
)


def _config(
    *, planner: str = "planner-model", synthesizer: str = "synth-model"
) -> LiveProviderConfig:
    return LiveProviderConfig(
        api_key="qk",
        planner=ModelRoleSettings(role=PLANNER_ROLE, model_id=planner),
        synthesizer=ModelRoleSettings(role=SYNTHESIZER_ROLE, model_id=synthesizer),
    )


def test_router_uses_planner_before_successful_tool_observation() -> None:
    router = ModelRouter(_config())
    steps = [
        AgentStep(step_index=0, state=AgentState.RUNNING),
        AgentStep(
            step_index=1,
            state=AgentState.TOOL_CALL,
            tool_name="rag.search",
            tool_result=ToolResult.failure("timeout: synthetic"),
        ),
    ]
    routed = router.route(steps)
    assert routed.role == PLANNER_ROLE
    assert routed.model_id == "planner-model"
    assert routed.backend == "openai_responses"
    assert routed.routing_status == ROUTING_DISTINCT


def test_router_uses_synthesizer_after_successful_tool_observation() -> None:
    router = ModelRouter(_config())
    steps = [
        AgentStep(
            step_index=0,
            state=AgentState.TOOL_CALL,
            tool_name="rag.search",
            tool_result=ToolResult.success({"chunks": []}),
        )
    ]
    routed = router.route(steps)
    assert routed.role == SYNTHESIZER_ROLE
    assert routed.model_id == "synth-model"
    assert routed.routing_status == ROUTING_DISTINCT


def test_same_model_ids_are_marked_degraded() -> None:
    router = ModelRouter(_config(planner="same-model", synthesizer="same-model"))
    routed = router.route([])
    assert routed.routing_status == ROUTING_DEGRADED
    assert routed.model_id == "same-model"


def test_routing_policy_does_not_inspect_model_name_substrings() -> None:
    router = ModelRouter(
        _config(planner="contains-synth-marker", synthesizer="contains-plan-marker")
    )
    assert router.select_role([]) == PLANNER_ROLE
    assert router.route([]).model_id == "contains-synth-marker"
    success = [
        AgentStep(
            step_index=0,
            state=AgentState.TOOL_CALL,
            tool_name="learner.get_profile",
            tool_result=ToolResult.success({"ok": True}),
        )
    ]
    assert router.select_role(success) == SYNTHESIZER_ROLE
    assert router.route(success).model_id == "contains-plan-marker"
