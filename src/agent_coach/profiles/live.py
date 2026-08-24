"""In-process composition for the optional live-provider diploma profile."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from agent_coach.core import AgentRunner, RunLimits, RunRequest, ToolAccess, ToolSpec
from agent_coach.core.contracts import (
    ToolContext,
    ToolResult,
    tool_specs_from_contract_bundle,
)
from agent_coach.core.security import DefaultSecurityPolicy
from agent_coach.provider.config import LiveProviderConfig, load_live_provider_config
from agent_coach.provider.errors import (
    UNKNOWN_PRICING_MESSAGE,
    LiveConfigurationError,
)
from agent_coach.provider.openai_responses import (
    OpenAIResponsesPlanner,
    ResponsesClientPort,
    build_official_responses_client,
)
from agent_coach.retrieval.composition import build_local_vector_index
from agent_coach.retrieval.contracts import RetrievalConfig
from agent_coach.retrieval.tool_adapter import LocalVectorRagTool

DEFAULT_CONTRACT_BUNDLE_RESOURCE = "agent_contract_bundle.json"
LIVE_PROFILE_NAME = "live_provider"
LIVE_TOOL_NAMES = ("rag.search", "learner.get_profile")
DEMO_LEARNER_PROFILE = {
    "learning_goal": "Review public diploma notes",
    "preferred_style": "short_grounded_citations",
    "mastery_level": "beginner",
    "contains_learner_data": False,
}


@dataclass(frozen=True)
class LiveComposition:
    """Runner wired to native Responses function calling and local tools."""

    runner: AgentRunner
    request: RunRequest
    planner: OpenAIResponsesPlanner
    tools: tuple[ToolSpec, ...]
    config: LiveProviderConfig
    routing_status: str


class LiveReadOnlyToolAdapter:
    """Dispatch advertised live tools without write side effects."""

    def __init__(self, rag_tool: LocalVectorRagTool) -> None:
        self._rag_tool = rag_tool

    def execute(
        self,
        tool: ToolSpec,
        args: Mapping[str, object],
        context: ToolContext,
    ) -> ToolResult:
        if tool.access is not ToolAccess.READ:
            return ToolResult.failure(
                "security: live adapter refuses write-enabled tools",
                category="security",
            )
        if tool.name == "rag.search":
            return self._rag_tool.execute(tool, args, context)
        if tool.name == "learner.get_profile":
            if args:
                return ToolResult.failure(
                    "validation: learner.get_profile accepts no arguments",
                    category="validation",
                )
            del context
            return ToolResult.success(dict(DEMO_LEARNER_PROFILE), sources=[])
        return ToolResult.failure(
            f"validation: live adapter does not execute {tool.name}",
            category="validation",
        )


def advertised_live_tools(
    *,
    contract_bundle_path: Path | None = None,
) -> tuple[ToolSpec, ...]:
    """Return the frozen read-only live subset from the D2 bundle."""

    bundle_text = (
        resources.files("agent_coach.data")
        .joinpath(DEFAULT_CONTRACT_BUNDLE_RESOURCE)
        .read_text(encoding="utf-8")
        if contract_bundle_path is None
        else contract_bundle_path.read_text(encoding="utf-8")
    )
    by_name = {
        tool.name: tool
        for tool in tool_specs_from_contract_bundle(json.loads(bundle_text))
    }
    selected: list[ToolSpec] = []
    for name in LIVE_TOOL_NAMES:
        tool = by_name.get(name)
        if tool is None:
            raise ValueError(f"live tool is absent from read-only contract: {name}")
        if tool.access is not ToolAccess.READ:
            raise ValueError(f"live tool is not read-only: {name}")
        selected.append(tool)
    return tuple(selected)


def build_live_composition(
    question: str,
    *,
    config: LiveProviderConfig | None = None,
    environ: Mapping[str, str] | None = None,
    client: ResponsesClientPort | None = None,
    retrieval_config: RetrievalConfig | None = None,
    corpus_path: Path | None = None,
    contract_bundle_path: Path | None = None,
    run_id: str = "live-provider-demo",
) -> LiveComposition:
    """Wire AgentRunner to the optional live-provider profile.

    A missing SDK, API key or injected client fails closed. This composition
    never falls back to the deterministic mock planner.
    """

    settings = (
        config
        if config is not None
        else load_live_provider_config(environ, require_api_key=client is None)
    )
    if len(question) > settings.max_question_chars:
        raise LiveConfigurationError(
            "invalid_config",
            "live question exceeds AGENT_COACH_LIVE_MAX_QUESTION_CHARS",
        )
    if settings.cost_cap_usd > 0:
        raise LiveConfigurationError(
            "unknown_pricing_cost_cap",
            UNKNOWN_PRICING_MESSAGE,
        )
    resolved_client = (
        client if client is not None else build_official_responses_client(settings)
    )
    store, knowledge_base = build_local_vector_index(
        config=retrieval_config,
        corpus_path=corpus_path,
    )
    tools = advertised_live_tools(contract_bundle_path=contract_bundle_path)
    planner = OpenAIResponsesPlanner(settings, resolved_client)
    runner = AgentRunner(
        planner=planner,
        tools=tools,
        tool_executor=LiveReadOnlyToolAdapter(
            LocalVectorRagTool(store, knowledge_base, config=retrieval_config)
        ),
        security_policy=DefaultSecurityPolicy(),
    )
    request = RunRequest(
        question=question,
        user_id="demo-user",
        session_id="demo-session",
        run_id=run_id,
        query_options={"adapter_profile": LIVE_PROFILE_NAME},
        limits=RunLimits(
            max_steps=6,
            max_time_sec=settings.run_time_limit_sec,
            max_tokens=settings.max_run_tokens,
            tool_error_limit=2,
        ),
    )
    return LiveComposition(
        runner=runner,
        request=request,
        planner=planner,
        tools=tools,
        config=settings,
        routing_status=settings.routing_status,
    )
