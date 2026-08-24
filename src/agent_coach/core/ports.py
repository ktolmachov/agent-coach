"""Typed ports around the framework-independent Agent Core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TypeAlias, runtime_checkable

from agent_coach.core.contracts import (
    AgentRunResult,
    AgentStep,
    PlannerCallResult,
    RunRequest,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from agent_coach.core.stop_controller import RunState

Message: TypeAlias = Mapping[str, object]
TokenUsage: TypeAlias = Mapping[str, int]


@runtime_checkable
class PlannerPort(Protocol):
    """Decision backend used by the agent loop."""

    def decide(
        self,
        messages: Sequence[Message],
        *,
        steps: Sequence[AgentStep],
        tools: Sequence[ToolSpec],
    ) -> PlannerCallResult:
        """Return one normalized decision plus usage and routing metadata."""


@runtime_checkable
class MessageBuilderPort(Protocol):
    """Prompt/context reconstruction boundary."""

    def build_messages(
        self,
        request: RunRequest,
        *,
        steps: Sequence[AgentStep],
        tools: Sequence[ToolSpec],
    ) -> list[Message]:
        """Build planner messages for the current run state."""


@runtime_checkable
class SecurityPolicyPort(Protocol):
    """Tool argument/result and final-answer security boundary."""

    def validate_tool_args(self, tool: ToolSpec, args: Mapping[str, object]) -> None:
        """Raise ``ValueError`` when planner-supplied args are unsafe."""

    def secure_tool_result(self, result: ToolResult) -> ToolResult:
        """Return sanitized tool output safe for traces and future prompts."""

    def guard_final_answer(
        self, answer: str, sources: list[dict[str, object]]
    ) -> tuple[str, bool, bool, bool]:
        """Return ``(answer, redacted, fallback, rejected)``."""

    def fallback_answer(self, code: str, default: str) -> str:
        """Return a stable fallback answer for one guardrail code."""


@runtime_checkable
class ToolExecutionPort(Protocol):
    """Tool invocation boundary."""

    def execute(
        self,
        tool: ToolSpec,
        args: Mapping[str, object],
        context: ToolContext,
    ) -> ToolResult:
        """Execute one already-validated tool call."""


@runtime_checkable
class UsageAccountingPort(Protocol):
    """Token, pricing and budget accounting boundary."""

    def account_planner_usage(
        self, state: RunState, usage: TokenUsage | None
    ) -> None:
        """Accumulate planner tokens/cost into the mutable run state."""

    def account_tool_usage(self, state: RunState, result: ToolResult) -> None:
        """Accumulate tool-internal token/cost metadata into the run state."""


@runtime_checkable
class ClockPort(Protocol):
    """Clock boundary used by the runner."""

    def perf_counter(self) -> float:
        """Return monotonic seconds."""


@runtime_checkable
class RunStorePort(Protocol):
    """Persistence/event boundary for run projections."""

    def record_started(self, request: RunRequest) -> None:
        """Observe a new run."""

    def record_step(self, request: RunRequest, step: AgentStep) -> None:
        """Observe a completed step."""

    def record_completed(self, request: RunRequest, result: AgentRunResult) -> None:
        """Observe a terminal result."""
