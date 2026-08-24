"""In-process composition root for the local-vector diploma profile."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from agent_coach.core import AgentRunner, RunLimits, RunRequest, ToolSpec
from agent_coach.core.contracts import (
    AgentStep,
    PlannerCallResult,
    PlannerDecision,
    tool_specs_from_contract_bundle,
)
from agent_coach.core.ports import Message
from agent_coach.core.security import DefaultSecurityPolicy
from agent_coach.retrieval.contracts import DiplomaKnowledgeBase, RetrievalConfig
from agent_coach.retrieval.corpus import load_diploma_knowledge_base
from agent_coach.retrieval.store import InMemoryCosineStore
from agent_coach.retrieval.tool_adapter import LocalVectorRagTool

DEFAULT_CONTRACT_BUNDLE_RESOURCE = "agent_contract_bundle.json"
LOCAL_VECTOR_TOOL_NAME = "rag.search"


@dataclass(frozen=True)
class LocalVectorComposition:
    """Runner wired to real in-memory vector retrieval."""

    runner: AgentRunner
    request: RunRequest
    store: InMemoryCosineStore
    tools: tuple[ToolSpec, ...]
    config: RetrievalConfig
    corpus_hash: str
    corpus_version: str
    index_fingerprint: str


class LocalVectorQuestionPlanner:
    """Scripted planner that forwards the real question into ``rag.search``.

    This is not provider-native function calling. D8 only proves that an
    arbitrary question changes retrieval. Live routing belongs to a later slice.
    """

    def decide(
        self,
        messages: Sequence[Message],
        *,
        steps: Sequence[AgentStep],
        tools: Sequence[ToolSpec],
    ) -> PlannerCallResult:
        del tools
        usage = {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
        if not any(step.tool_name == LOCAL_VECTOR_TOOL_NAME for step in steps):
            return PlannerCallResult(
                decision=PlannerDecision(
                    action="tool_call",
                    thought="Retrieve public notes for the learner question.",
                    tool_name=LOCAL_VECTOR_TOOL_NAME,
                    tool_args={"query": _user_question(messages)},
                ),
                token_usage=usage,
            )
        search = next(
            (
                step
                for step in reversed(steps)
                if step.tool_name == LOCAL_VECTOR_TOOL_NAME
            ),
            None,
        )
        excerpt = _safe_excerpt(search)
        if excerpt:
            return PlannerCallResult(
                decision=PlannerDecision(
                    action="final_answer",
                    thought="Cite the retrieved public note.",
                    final_answer=f"{excerpt} [1]",
                ),
                token_usage=usage,
            )
        return PlannerCallResult(
            decision=PlannerDecision(
                action="final_answer",
                thought="No safe retrieval evidence.",
                final_answer="I cannot answer from the provided sources.",
            ),
            token_usage=usage,
        )


def advertised_local_vector_tools(
    *,
    contract_bundle_path: Path | None = None,
) -> tuple[ToolSpec, ...]:
    """Return the frozen public ``rag.search`` spec only."""

    bundle_text = (
        resources.files("agent_coach.data")
        .joinpath(DEFAULT_CONTRACT_BUNDLE_RESOURCE)
        .read_text(encoding="utf-8")
        if contract_bundle_path is None
        else contract_bundle_path.read_text(encoding="utf-8")
    )
    bundle_tools = tool_specs_from_contract_bundle(json.loads(bundle_text))
    tools = {tool.name: tool for tool in bundle_tools}
    search = tools.get(LOCAL_VECTOR_TOOL_NAME)
    if search is None:
        raise ValueError("rag.search is absent from the read-only contract")
    return (search,)


def build_local_vector_index(
    *,
    config: RetrievalConfig | None = None,
    corpus_path: Path | None = None,
) -> tuple[InMemoryCosineStore, DiplomaKnowledgeBase]:
    """Build an idempotent in-memory index from the packaged corpus."""

    limits = config if config is not None else RetrievalConfig()
    knowledge_base = load_diploma_knowledge_base(corpus_path, config=limits)
    store = InMemoryCosineStore(config=limits)
    store.build(knowledge_base.chunks)
    return store, knowledge_base


def build_local_vector_composition(
    question: str,
    *,
    config: RetrievalConfig | None = None,
    corpus_path: Path | None = None,
    contract_bundle_path: Path | None = None,
    run_id: str = "local-vector-demo",
) -> LocalVectorComposition:
    """Wire AgentRunner to local-vector ``rag.search`` without changing Core."""

    limits = config if config is not None else RetrievalConfig()
    store, knowledge_base = build_local_vector_index(
        config=limits,
        corpus_path=corpus_path,
    )
    tools = advertised_local_vector_tools(contract_bundle_path=contract_bundle_path)
    runner = AgentRunner(
        planner=LocalVectorQuestionPlanner(),
        tools=tools,
        tool_executor=LocalVectorRagTool(store, knowledge_base, config=limits),
        security_policy=DefaultSecurityPolicy(),
    )
    request = RunRequest(
        question=question,
        user_id="demo-user",
        session_id="demo-session",
        run_id=run_id,
        query_options={"adapter_profile": "local_vector"},
        limits=RunLimits(max_steps=4, tool_error_limit=2),
    )
    return LocalVectorComposition(
        runner=runner,
        request=request,
        store=store,
        tools=tools,
        config=limits,
        corpus_hash=knowledge_base.corpus_hash,
        corpus_version=knowledge_base.corpus_version,
        index_fingerprint=store.index_fingerprint,
    )


def _user_question(messages: Sequence[Message]) -> str:
    for message in messages:
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _safe_excerpt(step: AgentStep | None) -> str:
    if (
        step is None
        or step.tool_result is None
        or not step.tool_result.ok
        or step.tool_result.meta.get("has_evidence") is not True
    ):
        return ""
    excerpt = step.tool_result.meta.get("excerpt")
    if not isinstance(excerpt, str):
        return ""
    compact = " ".join(excerpt.split())
    if not compact:
        return ""
    return compact if len(compact) <= 240 else compact[:237] + "..."
