"""Framework-independent Agent Core runner."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from agent_coach.core.contracts import (
    AgentRunResult,
    AgentState,
    AgentStep,
    PlannerDecision,
    RunRequest,
    StopReason,
    ToolAccess,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from agent_coach.core.ports import (
    ClockPort,
    Message,
    MessageBuilderPort,
    PlannerPort,
    RunStorePort,
    SecurityPolicyPort,
    ToolExecutionPort,
    UsageAccountingPort,
)
from agent_coach.core.security import (
    DEFAULT_FALLBACK_ANSWER,
    DefaultSecurityPolicy,
    redacted_mapping,
    sanitize_identifier,
    trace_text,
)
from agent_coach.core.stop_controller import RunState, evaluate_stop
from agent_coach.core.text import merge_sources


class SystemClock:
    """Default monotonic clock."""

    def perf_counter(self) -> float:
        return time.perf_counter()


class SimpleMessageBuilder:
    """Minimal message builder that keeps the core runnable without a framework."""

    def build_messages(
        self,
        request: RunRequest,
        *,
        steps: Sequence[AgentStep],
        tools: Sequence[ToolSpec],
    ) -> list[Message]:
        return [
            {
                "role": "system",
                "content": "Use only declared tools and cite source labels.",
                "tools": [tool.name for tool in tools],
            },
            {"role": "user", "content": request.question},
            {"role": "assistant_trace", "step_count": len(steps)},
        ]


class SimpleUsageAccounting:
    """Standard-library-only usage accumulation."""

    def account_planner_usage(
        self, state: RunState, usage: Mapping[str, int] | None
    ) -> None:
        if usage:
            _add_tokens(state, usage)

    def account_tool_usage(self, state: RunState, result: ToolResult) -> None:
        usage = result.meta.get("token_usage")
        if isinstance(usage, Mapping):
            _add_tokens(state, usage)
        cost = result.meta.get("estimated_cost_usd")
        if (
            isinstance(cost, int | float)
            and not isinstance(cost, bool)
            and cost >= 0
        ):
            state.total_cost_usd += float(cost)
            state.known_cost_usd += float(cost)
            state.saw_priced_usage = True


class NullRunStore:
    """No-op store for embedded or test composition roots."""

    def record_started(self, request: RunRequest) -> None:
        del request

    def record_step(self, request: RunRequest, step: AgentStep) -> None:
        del request, step

    def record_completed(self, request: RunRequest, result: AgentRunResult) -> None:
        del request, result


class AgentRunner:
    """Pure orchestration loop behind explicit ports."""

    def __init__(
        self,
        *,
        planner: PlannerPort,
        tools: Sequence[ToolSpec],
        tool_executor: ToolExecutionPort,
        message_builder: MessageBuilderPort | None = None,
        security_policy: SecurityPolicyPort | None = None,
        usage_accounting: UsageAccountingPort | None = None,
        clock: ClockPort | None = None,
        run_store: RunStorePort | None = None,
    ) -> None:
        self._planner = planner
        self._tools = list(tools)
        self._tool_by_name = {tool.name: tool for tool in tools}
        self._tool_executor = tool_executor
        self._message_builder = (
            message_builder if message_builder is not None else SimpleMessageBuilder()
        )
        self._security = (
            security_policy if security_policy is not None else DefaultSecurityPolicy()
        )
        self._usage = usage_accounting if usage_accounting is not None else (
            SimpleUsageAccounting()
        )
        self._clock = clock if clock is not None else SystemClock()
        self._store = run_store if run_store is not None else NullRunStore()

    def run(self, request: RunRequest) -> AgentRunResult:
        if not request.run_id:
            return self._request_failure(
                request,
                StopReason.INVALID_DECISION,
                "run_id is required for deterministic core execution",
            )
        request = RunRequest(
            question=request.question,
            user_id=request.user_id,
            session_id=request.session_id,
            run_id=request.run_id,
            query_options=dict(request.query_options),
            limits=request.limits,
        )
        started_at, clock_error = self._clock_now()
        if clock_error:
            return self._request_failure(request, StopReason.LLM_ERROR, clock_error)
        state = RunState(limits=request.limits, started_at=started_at)
        context = ToolContext(
            user_id=request.user_id,
            question=request.question,
            query_options=dict(request.query_options),
            session_id=request.session_id,
            run_id=request.run_id,
        )
        steps: list[AgentStep] = []
        sources: list[dict[str, object]] = []
        store_error = self._record_started(request)
        if store_error:
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=StopReason.LLM_ERROR,
                detail=store_error,
                answer_fallback=True,
            )

        while True:
            now, clock_error = self._clock_now()
            if clock_error:
                return self._finish(
                    request,
                    state,
                    answer=DEFAULT_FALLBACK_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=StopReason.LLM_ERROR,
                    detail=clock_error,
                    answer_fallback=True,
                )
            stop = evaluate_stop(
                state,
                include_step_limit=True,
                now_monotonic=now,
            )
            if stop.stop:
                return self._finish(
                    request,
                    state,
                    answer=DEFAULT_FALLBACK_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=stop.reason or StopReason.MAX_STEPS,
                    detail=stop.detail,
                    answer_fallback=True,
                )

            step = AgentStep(step_index=state.step_count, state=AgentState.RUNNING)
            steps.append(step)
            state.step_count += 1
            try:
                messages = self._message_builder.build_messages(
                    request, steps=steps, tools=self._tools
                )
                decision, usage = self._planner.decide(
                    messages, steps=steps, tools=self._tools
                )
                if not isinstance(decision, PlannerDecision):
                    raise TypeError("planner returned malformed decision")
            except Exception as exc:  # noqa: BLE001 - ports normalize external failures
                step.state = AgentState.STOPPED
                step.error = trace_text(exc)
                store_error = self._record_step(request, step)
                if store_error:
                    step.error = store_error
                return self._finish(
                    request,
                    state,
                    answer=DEFAULT_FALLBACK_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=StopReason.LLM_ERROR,
                    detail=store_error or step.error or "",
                    answer_fallback=True,
                )
            step.thought = trace_text(decision.thought)
            step.decision_raw = None
            usage_error = self._account_planner_usage(state, usage)
            if usage_error:
                step.state = AgentState.STOPPED
                step.error = usage_error
                store_error = self._record_step(request, step)
                return self._finish(
                    request,
                    state,
                    answer=DEFAULT_FALLBACK_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=StopReason.LLM_ERROR,
                    detail=store_error or usage_error,
                    answer_fallback=True,
                )

            if decision.action == "final_answer":
                step.state = AgentState.COMPLETED
                store_error = self._record_step(request, step)
                if store_error:
                    step.state = AgentState.STOPPED
                    step.error = store_error
                    return self._finish(
                        request,
                        state,
                        answer=DEFAULT_FALLBACK_ANSWER,
                        sources=sources,
                        steps=steps,
                        reason=StopReason.LLM_ERROR,
                        detail=store_error,
                        answer_fallback=True,
                    )
                return self._complete_answer(
                    request, state, decision, sources=sources, steps=steps
                )
            if decision.action != "tool_call":
                step.state = AgentState.STOPPED
                step.error = trace_text(f"invalid action: {decision.action!r}")
                store_error = self._record_step(request, step)
                if store_error:
                    step.error = store_error
                    return self._finish(
                        request,
                        state,
                        answer=DEFAULT_FALLBACK_ANSWER,
                        sources=sources,
                        steps=steps,
                        reason=StopReason.LLM_ERROR,
                        detail=store_error,
                        answer_fallback=True,
                    )
                return self._finish(
                    request,
                    state,
                    answer=DEFAULT_FALLBACK_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=StopReason.INVALID_DECISION,
                    detail=step.error,
                    answer_fallback=True,
                )

            result = self._handle_tool_call(
                request, state, context, decision, step, steps, sources
            )
            store_error = self._record_step(request, step)
            if store_error:
                step.state = AgentState.STOPPED
                step.error = store_error
                return self._finish(
                    request,
                    state,
                    answer=DEFAULT_FALLBACK_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=StopReason.LLM_ERROR,
                    detail=store_error,
                    answer_fallback=True,
                )
            if result is not None:
                store_error = self._record_completed(request, result)
                if store_error:
                    result.trace["store_error"] = store_error
                return result
            if step.tool_result is not None:
                result_sources = step.tool_result.meta.get("sources")
                if isinstance(result_sources, list):
                    merge_sources(sources, result_sources, max_sources=12)

    def _handle_tool_call(
        self,
        request: RunRequest,
        state: RunState,
        context: ToolContext,
        decision: PlannerDecision,
        step: AgentStep,
        steps: list[AgentStep],
        sources: list[dict[str, object]],
    ) -> AgentRunResult | None:
        raw_tool_name = decision.tool_name or ""
        tool_name = sanitize_identifier(raw_tool_name)
        step.state = AgentState.TOOL_CALL
        step.tool_name = tool_name
        if not isinstance(decision.tool_args, dict):
            step.state = AgentState.STOPPED
            step.error = "tool args must be an object"
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=StopReason.INVALID_DECISION,
                detail=step.error,
                answer_fallback=True,
                record_completed=False,
            )
        raw_args = dict(decision.tool_args)
        step.tool_args = redacted_mapping(raw_args)
        tool = self._tool_by_name.get(raw_tool_name)
        if tool is None:
            step.state = AgentState.STOPPED
            step.error = f"unknown tool: {tool_name!r}"
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=StopReason.UNKNOWN_TOOL,
                detail=step.error,
                answer_fallback=True,
                record_completed=False,
            )
        try:
            self._security.validate_tool_args(tool, raw_args)
        except Exception as exc:  # noqa: BLE001 - security port is fail-closed
            step.state = AgentState.STOPPED
            step.error = trace_text(exc)
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=StopReason.INVALID_DECISION,
                detail=step.error,
                answer_fallback=True,
                record_completed=False,
            )
        if tool.access is ToolAccess.WRITE:
            step.state = AgentState.NEEDS_HUMAN
            step.error = "write tool requires human approval"
            return self._finish(
                request,
                state,
                answer="Write action is pending human approval.",
                sources=sources,
                steps=steps,
                reason=StopReason.NEEDS_HUMAN,
                detail=step.error,
                answer_fallback=True,
                record_completed=False,
            )
        if state.is_duplicate_call(raw_tool_name, raw_args):
            step.state = AgentState.STOPPED
            step.error = "repeated tool call"
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=StopReason.REPEATED_TOOL_CALL,
                detail=step.error,
                answer_fallback=True,
                record_completed=False,
            )
        state.record_tool_call(raw_tool_name, raw_args)
        try:
            raw_result = self._tool_executor.execute(tool, raw_args, context)
            if not isinstance(raw_result, ToolResult):
                raise TypeError("tool executor returned malformed result")
            secure_result = self._security.secure_tool_result(raw_result)
            if not isinstance(secure_result, ToolResult):
                raise TypeError("security policy returned malformed tool result")
        except Exception as exc:  # noqa: BLE001 - port failures become terminal results
            step.state = AgentState.STOPPED
            step.error = trace_text(exc)
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=StopReason.TOOL_ERROR_LIMIT,
                detail=step.error,
                answer_fallback=True,
                record_completed=False,
            )
        step.tool_result = secure_result
        usage_error = self._account_tool_usage(state, secure_result)
        if usage_error:
            step.state = AgentState.STOPPED
            step.error = usage_error
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=StopReason.TOOL_ERROR_LIMIT,
                detail=usage_error,
                answer_fallback=True,
                record_completed=False,
            )
        if secure_result.ok:
            state.reset_tool_errors()
        else:
            state.increment_tool_error()
        now, clock_error = self._clock_now()
        if clock_error:
            step.state = AgentState.STOPPED
            step.error = clock_error
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=StopReason.LLM_ERROR,
                detail=clock_error,
                answer_fallback=True,
                record_completed=False,
            )
        stop = evaluate_stop(
            state,
            include_step_limit=False,
            now_monotonic=now,
        )
        if stop.stop:
            step.state = AgentState.STOPPED
            return self._finish(
                request,
                state,
                answer=DEFAULT_FALLBACK_ANSWER,
                sources=sources,
                steps=steps,
                reason=stop.reason or StopReason.TOOL_ERROR_LIMIT,
                detail=stop.detail,
                answer_fallback=True,
                record_completed=False,
            )
        return None

    def _complete_answer(
        self,
        request: RunRequest,
        state: RunState,
        decision: PlannerDecision,
        *,
        sources: list[dict[str, object]],
        steps: list[AgentStep],
    ) -> AgentRunResult:
        answer = decision.final_answer or ""
        try:
            guard_result = self._security.guard_final_answer(answer, sources)
            if (
                not isinstance(guard_result, tuple)
                or len(guard_result) != 4
                or not isinstance(guard_result[0], str)
            ):
                raise TypeError("security policy returned malformed final guardrail")
            guarded, redacted, output_fallback, rejected = guard_result
        except Exception as exc:  # noqa: BLE001 - final security fails closed
            state.guardrail_triggered = True
            guarded = self._safe_fallback_answer("guardrail_error")
            redacted = False
            output_fallback = True
            rejected = True
            extra_detail = trace_text(exc)
        else:
            extra_detail = "output guardrail rejected final answer"
        if rejected:
            state.guardrail_triggered = True
            return self._finish(
                request,
                state,
                answer=guarded,
                sources=sources,
                steps=steps,
                reason=StopReason.GUARDRAIL_TRIGGERED,
                detail=extra_detail,
                answer_fallback=True,
                extra_trace={
                    "guardrail_redacted": redacted,
                    "output_fallback": output_fallback,
                },
            )
        return self._finish(
            request,
            state,
            answer=guarded,
            sources=sources,
            steps=steps,
            reason=StopReason.COMPLETED,
            answer_fallback=decision.fallback or output_fallback,
            extra_trace={
                "guardrail_redacted": redacted,
                "output_fallback": output_fallback,
            },
        )

    def _finish(
        self,
        request: RunRequest,
        state: RunState,
        *,
        answer: str,
        sources: list[dict[str, object]],
        steps: list[AgentStep],
        reason: StopReason,
        detail: str = "",
        answer_fallback: bool = False,
        extra_trace: dict[str, object] | None = None,
        record_completed: bool = True,
    ) -> AgentRunResult:
        now, clock_error = self._clock_now()
        trace: dict[str, object] = {
            "run_id": request.run_id,
            "stop_reason": reason.value,
            "stop_detail": detail,
            "step_count": state.step_count,
            "tool_calls": [step.tool_name for step in steps if step.tool_name],
            "prompt_tokens": state.prompt_tokens,
            "completion_tokens": state.completion_tokens,
            "total_tokens": state.total_tokens,
            "total_cost_usd": state.total_cost_usd if state.saw_priced_usage else None,
            "cost_status": "estimated" if state.saw_priced_usage else "unknown",
            "source_count": len(sources),
            "duration_ms": round(
                ((now or state.started_at) - state.started_at) * 1000, 3
            ),
        }
        if clock_error:
            trace["clock_error"] = clock_error
        if extra_trace:
            trace.update(extra_trace)
        result = AgentRunResult(
            answer=answer,
            sources=sources,
            steps=steps,
            stop_reason=reason,
            state=_state_for_stop_reason(reason),
            trace=trace,
            answer_fallback=answer_fallback,
        )
        if reason.is_success and result.answer_status == "abstain":
            result.answer = self._safe_fallback_answer("grounded_abstain")
            result.answer_fallback = True
            result.trace["abstention_enforced"] = True
        result.trace["success"] = result.success
        result.trace["answer_status"] = result.answer_status
        if not record_completed:
            return result
        store_error = self._record_completed(request, result)
        if store_error:
            result.trace["store_error"] = store_error
        return result

    def _request_failure(
        self, request: RunRequest, reason: StopReason, detail: str
    ) -> AgentRunResult:
        trace = {
            "run_id": request.run_id,
            "stop_reason": reason.value,
            "stop_detail": detail,
            "step_count": 0,
            "tool_calls": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": None,
            "cost_status": "unknown",
            "source_count": 0,
            "duration_ms": 0.0,
            "success": False,
            "answer_status": "abstain",
        }
        return AgentRunResult(
            answer=DEFAULT_FALLBACK_ANSWER,
            sources=[],
            steps=[],
            stop_reason=reason,
            state=_state_for_stop_reason(reason),
            trace=trace,
            answer_fallback=True,
        )

    def _record_started(self, request: RunRequest) -> str:
        try:
            self._store.record_started(request)
        except Exception as exc:  # noqa: BLE001 - store failures are bounded
            return trace_text(exc)
        return ""

    def _clock_now(self) -> tuple[float, str]:
        try:
            value = self._clock.perf_counter()
        except Exception as exc:  # noqa: BLE001 - clock failures are bounded
            return 0.0, trace_text(exc)
        if not isinstance(value, int | float) or isinstance(value, bool):
            return 0.0, "clock returned malformed value"
        return float(value), ""

    def _safe_fallback_answer(self, code: str) -> str:
        try:
            answer = self._security.fallback_answer(code, DEFAULT_FALLBACK_ANSWER)
        except Exception:  # noqa: BLE001 - fallback failures use package default
            return DEFAULT_FALLBACK_ANSWER
        if not isinstance(answer, str) or not answer.strip():
            return DEFAULT_FALLBACK_ANSWER
        return answer

    def _record_step(self, request: RunRequest, step: AgentStep) -> str:
        try:
            self._store.record_step(request, step)
        except Exception as exc:  # noqa: BLE001 - store failures are bounded
            return trace_text(exc)
        return ""

    def _record_completed(self, request: RunRequest, result: AgentRunResult) -> str:
        try:
            self._store.record_completed(request, result)
        except Exception as exc:  # noqa: BLE001 - store failures are bounded
            return trace_text(exc)
        return ""

    def _account_planner_usage(
        self, state: RunState, usage: Mapping[str, int] | None
    ) -> str:
        try:
            self._usage.account_planner_usage(state, usage)
        except Exception as exc:  # noqa: BLE001 - usage port failures are bounded
            return trace_text(exc)
        return ""

    def _account_tool_usage(self, state: RunState, result: ToolResult) -> str:
        try:
            self._usage.account_tool_usage(state, result)
        except Exception as exc:  # noqa: BLE001 - usage port failures are bounded
            return trace_text(exc)
        return ""


def _add_tokens(state: RunState, usage: Mapping[str, int]) -> None:
    prompt = _nonnegative_int(usage.get("prompt_tokens"))
    completion = _nonnegative_int(usage.get("completion_tokens"))
    total = _nonnegative_int(usage.get("total_tokens")) or prompt + completion
    state.prompt_tokens += prompt
    state.completion_tokens += completion
    state.total_tokens += total


def _nonnegative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return 0


def _state_for_stop_reason(reason: StopReason) -> AgentState:
    if reason.is_success:
        return AgentState.COMPLETED
    if reason is StopReason.NEEDS_HUMAN:
        return AgentState.NEEDS_HUMAN
    return AgentState.STOPPED
