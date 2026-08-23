"""Public data contracts for the standalone Agent Core.

Provenance: distilled from HomeTutor ``app.agent.contracts`` at
292be74f97b18615388838c2a1ddf2e0879585e0 and the exported
``agent-contracts/1.0.0`` bundle. The implementation is intentionally
framework-independent and does not import HomeTutor runtime modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePath
from typing import Any

CONTRACT_SCHEMA_VERSION = "agent-contracts/1.0.0"
CONTRACT_SCHEMA_HASH = (
    "218c90732c25ae2f9b26c4f5a9ea5ee81c28bf797299c99b53e310bf22315910"
)


class ToolAccess(StrEnum):
    """Access level declared by a tool contract."""

    READ = "read"
    WRITE = "write"


class StopReason(StrEnum):
    """Explicit terminal reason for an agent run."""

    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    MAX_TIME = "max_time"
    MAX_TOKENS = "max_tokens"
    MAX_COST = "max_cost"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    TOOL_ERROR_LIMIT = "tool_error_limit"
    INVALID_ARGS_AFTER_REPAIR = "invalid_args_after_repair"
    GUARDRAIL_TRIGGERED = "guardrail_triggered"
    NEEDS_HUMAN = "needs_human"
    UNKNOWN_TOOL = "unknown_tool"
    LLM_ERROR = "llm_error"
    INVALID_DECISION = "invalid_decision"

    @property
    def is_success(self) -> bool:
        return self is StopReason.COMPLETED


class AgentState(StrEnum):
    """Finite states surfaced in public run projections."""

    RUNNING = "running"
    TOOL_CALL = "tool_call"
    REPAIRING = "repairing"
    NEEDS_HUMAN = "needs_human"
    STOPPED = "stopped"
    COMPLETED = "completed"


class AgentPhase(StrEnum):
    """Stable diploma trace phases."""

    SCENARIO_SELECTION = "scenario_selection"
    LEARNER_CONTEXT = "learner_context"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    PRACTICE_BRANCH = "practice_branch"
    FINAL_VALIDATION = "final_validation"


class PhaseStatus(StrEnum):
    """Outcome of one trace phase."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


_TOOL_PHASE_PREFIXES: tuple[tuple[str, AgentPhase], ...] = (
    ("learner.", AgentPhase.LEARNER_CONTEXT),
    ("progress.", AgentPhase.LEARNER_CONTEXT),
    ("konspekt.", AgentPhase.LEARNER_CONTEXT),
    ("rag.", AgentPhase.KNOWLEDGE_RETRIEVAL),
    ("catalog.", AgentPhase.KNOWLEDGE_RETRIEVAL),
    ("graph.", AgentPhase.KNOWLEDGE_RETRIEVAL),
    ("quiz.", AgentPhase.PRACTICE_BRANCH),
    ("cards.", AgentPhase.PRACTICE_BRANCH),
    ("sr.", AgentPhase.PRACTICE_BRANCH),
)


def phase_for_tool(tool_name: str | None) -> AgentPhase | None:
    """Map a dotted tool name to its owning diploma phase."""

    if not tool_name:
        return None
    for prefix, phase in _TOOL_PHASE_PREFIXES:
        if tool_name.startswith(prefix):
            return phase
    return None


@dataclass(frozen=True)
class ToolSpec:
    """Declarative tool contract consumed by the core runner."""

    name: str
    description: str
    when_to_use: str
    args_schema: dict[str, Any] = field(default_factory=dict)
    access: ToolAccess = ToolAccess.READ
    idempotent: bool = False
    limits: dict[str, Any] = field(default_factory=dict)

    @property
    def is_read_only(self) -> bool:
        return self.access is ToolAccess.READ


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a tool invocation."""

    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, data: Any = None, **meta: Any) -> ToolResult:
        return cls(ok=True, data=data, meta=dict(meta))

    @classmethod
    def failure(cls, error: str, **meta: Any) -> ToolResult:
        return cls(ok=False, error=error, meta=dict(meta))


@dataclass(frozen=True)
class ToolContext:
    """Harness-injected context. Planner decisions never supply these fields."""

    user_id: str
    question: str
    query_options: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class StopDecision:
    """Verdict returned by the stop controller."""

    stop: bool
    reason: StopReason | None = None
    detail: str = ""

    @classmethod
    def continue_run(cls) -> StopDecision:
        return cls(stop=False)

    @classmethod
    def halt(cls, reason: StopReason, detail: str = "") -> StopDecision:
        return cls(stop=True, reason=reason, detail=detail)


@dataclass(frozen=True)
class PlannerDecision:
    """Normalized planner output consumed by the runner."""

    action: str
    thought: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    final_answer: str | None = None
    raw: Any = None
    fallback: bool = False


@dataclass(frozen=True)
class RunLimits:
    """Pure budget limits for one run."""

    max_steps: int = 6
    max_time_sec: float = 0.0
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    tool_error_limit: int = 2


@dataclass(frozen=True)
class RunRequest:
    """Input accepted by the framework-independent core."""

    question: str
    user_id: str = "demo-user"
    session_id: str | None = None
    run_id: str | None = None
    query_options: dict[str, Any] = field(default_factory=dict)
    limits: RunLimits = field(default_factory=RunLimits)


@dataclass
class AgentStep:
    """One planner or tool step in a run trace."""

    step_index: int
    state: AgentState
    thought: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: ToolResult | None = None
    decision_raw: Any = None
    error: str | None = None


@dataclass
class AgentRunResult:
    """Final public result of an Agent Core run."""

    answer: str
    sources: list[dict[str, Any]]
    steps: list[AgentStep]
    stop_reason: StopReason
    state: AgentState
    trace: dict[str, Any] = field(default_factory=dict)
    answer_fallback: bool = False

    @property
    def is_success(self) -> bool:
        return self.success

    @property
    def has_successful_observation(self) -> bool:
        return any(step.tool_result and step.tool_result.ok for step in self.steps)

    @staticmethod
    def _source_label(source: Any) -> str | None:
        if isinstance(source, str):
            return source.strip() or None
        if not isinstance(source, dict):
            return None
        for key in ("file", "file_name", "source", "title", "url", "path"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @property
    def is_source_grounded(self) -> bool:
        return any(self._source_label(source) for source in self.sources)

    @property
    def has_grounding_observation(self) -> bool:
        return bool(self._grounding_sources())

    def _grounding_sources(self) -> list[Any]:
        grounding_sources: list[Any] = []
        for step in self.steps:
            result = step.tool_result
            if (
                result is None
                or not result.ok
                or phase_for_tool(step.tool_name) is not AgentPhase.KNOWLEDGE_RETRIEVAL
            ):
                continue
            result_sources = result.meta.get("sources")
            if not isinstance(result_sources, list):
                continue
            if not any(self._source_label(source) for source in result_sources):
                continue
            if result.meta.get("has_evidence") is True:
                grounding_sources.extend(result_sources)
                continue
        return grounding_sources

    @property
    def has_grounding_source_citation(self) -> bool:
        return self._has_citation_for_sources(self._grounding_sources())

    def _has_citation_for_sources(self, sources: list[Any]) -> bool:
        answer = self.answer.casefold()
        for source in sources:
            label = self._source_label(source)
            if not label:
                continue
            candidates = {label.casefold(), PurePath(label).name.casefold()}
            if any(candidate and candidate in answer for candidate in candidates):
                return True
            if isinstance(source, dict):
                index = source.get("cite_index") or source.get("index")
                if isinstance(index, int) and f"[{index}]" in answer:
                    return True
        return False

    @property
    def is_explicit_abstention(self) -> bool:
        normalized = " ".join(self.answer.casefold().split())
        abstain_markers = (
            "insufficient evidence",
            "not enough evidence",
            "cannot answer from the provided sources",
            "недостаточно данных",
            "не хватает данных",
        )
        return any(marker in normalized for marker in abstain_markers)

    @property
    def answer_status(self) -> str:
        if self.stop_reason is StopReason.GUARDRAIL_TRIGGERED:
            return "guardrails_fallback"
        if (
            self.stop_reason.is_success
            and not self.answer_fallback
            and not self.is_explicit_abstention
            and self.has_grounding_observation
            and self.is_source_grounded
            and self.has_grounding_source_citation
        ):
            return "grounded"
        return "abstain"

    @property
    def success(self) -> bool:
        return self.stop_reason.is_success and self.answer_status == "grounded"


def tool_specs_from_contract_bundle(
    bundle: dict[str, Any], *, include_write: bool = False
) -> list[ToolSpec]:
    """Build core tool specs from the exported D2 bundle."""

    if bundle.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported contract schema version")
    if bundle.get("schema_hash") != CONTRACT_SCHEMA_HASH:
        raise ValueError("unsupported contract schema hash")
    tools = bundle["contracts"]["tools"]
    raw_specs = list(tools["read_only_default"])
    if include_write:
        raw_specs.extend(tools["write_enabled_only"])
    return [
        ToolSpec(
            name=str(raw["name"]),
            description=str(raw.get("description") or ""),
            when_to_use=str(raw.get("when_to_use") or ""),
            args_schema=dict(raw.get("args_schema") or {}),
            access=ToolAccess(str(raw.get("access") or ToolAccess.READ.value)),
            idempotent=bool(raw.get("idempotent", False)),
            limits=dict(raw.get("limits") or {}),
        )
        for raw in raw_specs
    ]
