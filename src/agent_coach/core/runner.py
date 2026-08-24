"""Framework-independent Agent Core runner."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from agent_coach.core.contracts import (
    AgentPhase,
    AgentRunResult,
    AgentState,
    AgentStep,
    PhaseStatus,
    PlannerCallResult,
    PlannerDecision,
    PlannerRouting,
    RunRequest,
    StopReason,
    ToolAccess,
    ToolContext,
    ToolResult,
    ToolSpec,
    phase_for_tool,
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
        reset_error = self._reset_planner_run()
        if reset_error:
            return self._request_failure(request, StopReason.LLM_ERROR, reset_error)
        started_at, clock_error = self._clock_now()
        if clock_error:
            return self._request_failure(request, StopReason.LLM_ERROR, clock_error)
        state = RunState(limits=request.limits, started_at=started_at)
        if _is_unpriced_cloud_request(request):
            state.saw_unpriced_cloud_usage = True
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

            step = AgentStep(
                step_index=state.step_count,
                state=AgentState.RUNNING,
                started_at_ms=_elapsed_ms(state, now),
            )
            steps.append(step)
            state.step_count += 1
            try:
                messages = self._message_builder.build_messages(
                    request, steps=steps, tools=self._tools
                )
                messages = list(messages)
                messages.append(_budget_message(request, state, now_monotonic=now))
                call_result = self._planner.decide(
                    messages, steps=steps, tools=self._tools
                )
                if not isinstance(call_result, PlannerCallResult):
                    raise TypeError("planner returned malformed result")
                decision = call_result.decision
                usage = call_result.token_usage
                if not isinstance(decision, PlannerDecision):
                    raise TypeError("planner returned malformed decision")
                _record_routing(
                    state,
                    call_result.routing,
                    step_id=step.step_index,
                )
            except Exception as exc:  # noqa: BLE001 - ports normalize external failures
                failure_phase = _exception_phase(exc)
                if failure_phase is not None:
                    step.phase = failure_phase
                failure_routing = _exception_routing(exc)
                if failure_routing:
                    _record_routing(
                        state,
                        failure_routing,
                        step_id=step.step_index,
                    )
                usage_before = _usage_snapshot(state)
                usage_error = self._account_planner_usage(
                    state, _exception_token_usage(exc)
                )
                _record_step_usage_delta(
                    step, usage_before, _usage_snapshot(state)
                )
                step.state = AgentState.STOPPED
                step.error = usage_error or trace_text(exc)
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
            usage_before = _usage_snapshot(state)
            usage_error = self._account_planner_usage(state, usage)
            _record_step_usage_delta(step, usage_before, _usage_snapshot(state))
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
            now = state.started_at
            if request.limits.max_time_sec > 0:
                now, clock_error = self._clock_now()
                if clock_error:
                    step.state = AgentState.STOPPED
                    step.error = clock_error
                    store_error = self._record_step(request, step)
                    return self._finish(
                        request,
                        state,
                        answer=DEFAULT_FALLBACK_ANSWER,
                        sources=sources,
                        steps=steps,
                        reason=StopReason.LLM_ERROR,
                        detail=store_error or clock_error,
                        answer_fallback=True,
                    )
            stop = evaluate_stop(
                state,
                include_step_limit=False,
                now_monotonic=now,
            )
            if stop.stop:
                step.state = AgentState.STOPPED
                step.error = stop.detail
                store_error = self._record_step(request, step)
                return self._finish(
                    request,
                    state,
                    answer=DEFAULT_FALLBACK_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=stop.reason or StopReason.LLM_ERROR,
                    detail=store_error or stop.detail,
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
        usage_before = _usage_snapshot(state)
        usage_error = self._account_tool_usage(state, secure_result)
        _record_step_usage_delta(step, usage_before, _usage_snapshot(state))
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
        _close_step_duration(step, state, now)
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
        if not clock_error:
            _close_open_step_durations(steps, state, now)
        cost_status, total_cost = _cost_projection(state)
        trace: dict[str, object] = {
            "run_id": _trace_run_id(request),
            "stop_reason": reason.value,
            "stop_detail": detail,
            "step_count": state.step_count,
            "tool_calls": [step.tool_name for step in steps if step.tool_name],
            "prompt_tokens": state.prompt_tokens,
            "completion_tokens": state.completion_tokens,
            "total_tokens": state.total_tokens,
            "total_cost_usd": total_cost,
            "cost_status": cost_status,
            "source_count": len(sources),
            "duration_ms": round(
                ((now or state.started_at) - state.started_at) * 1000, 3
            ),
        }
        if state.model_routes:
            trace["model_routes"] = list(state.model_routes)
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
        result.trace["grounding"] = _grounding_summary(result)
        result.trace["phases"] = _phase_trace(result, request=request)
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
            "run_id": _trace_run_id(request),
            "stop_reason": reason.value,
            "stop_detail": detail,
            "step_count": 0,
            "tool_calls": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "cost_status": "local_zero",
            "source_count": 0,
            "duration_ms": 0.0,
            "success": False,
            "answer_status": "abstain",
        }
        result = AgentRunResult(
            answer=DEFAULT_FALLBACK_ANSWER,
            sources=[],
            steps=[],
            stop_reason=reason,
            state=_state_for_stop_reason(reason),
            trace=trace,
            answer_fallback=True,
        )
        result.trace["grounding"] = _grounding_summary(result)
        result.trace["phases"] = _phase_trace(result, request=request)
        return result

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

    def _reset_planner_run(self) -> str:
        reset = getattr(self._planner, "reset_run", None)
        if reset is None:
            return ""
        if not callable(reset):
            return "planner reset_run hook is not callable"
        try:
            reset()
        except Exception as exc:  # noqa: BLE001 - planner lifecycle is a port boundary
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


def _record_routing(
    state: RunState, routing: Sequence[PlannerRouting], *, step_id: int
) -> None:
    for route in routing:
        if not isinstance(route, PlannerRouting):
            raise TypeError("planner returned malformed routing")
        projection: dict[str, object] = {
            "step_id": step_id,
            "model_role": sanitize_identifier(route.model_role, max_chars=80),
            "model_id": sanitize_identifier(route.model_id, max_chars=80),
            "backend": sanitize_identifier(route.backend, max_chars=80),
            "routing_status": sanitize_identifier(
                route.routing_status, max_chars=80
            ),
        }
        if route.provider_call_id:
            projection["provider_call_id"] = sanitize_identifier(
                route.provider_call_id, max_chars=80
            )
        state.model_routes.append(projection)
        if projection["backend"] != "local":
            state.saw_unpriced_cloud_usage = True


def _trace_run_id(request: RunRequest) -> str | None:
    if request.run_id is None:
        return None
    return sanitize_identifier(request.run_id)


def _budget_message(
    request: RunRequest, state: RunState, *, now_monotonic: float
) -> Message:
    limits = request.limits
    elapsed = max(0.0, now_monotonic - state.started_at)
    remaining_steps = max(limits.max_steps - state.step_count, 0)
    remaining_time = (
        max(limits.max_time_sec - elapsed, 0.0)
        if limits.max_time_sec > 0
        else None
    )
    remaining_tokens = (
        max(limits.max_tokens - state.total_tokens, 0)
        if limits.max_tokens > 0
        else None
    )
    remaining_cost = (
        max(limits.max_cost_usd - state.total_cost_usd, 0.0)
        if limits.max_cost_usd > 0
        else None
    )
    return {
        "role": "runtime_budget",
        "remaining_steps": remaining_steps,
        "max_steps": limits.max_steps,
        "elapsed_sec": round(elapsed, 3),
        "remaining_time_sec": round(remaining_time, 3)
        if remaining_time is not None
        else None,
        "max_time_sec": limits.max_time_sec,
        "prompt_tokens": state.prompt_tokens,
        "completion_tokens": state.completion_tokens,
        "total_tokens": state.total_tokens,
        "remaining_tokens": remaining_tokens,
        "max_tokens": limits.max_tokens,
        "total_cost_usd": round(state.total_cost_usd, 6),
        "remaining_cost_usd": round(remaining_cost, 6)
        if remaining_cost is not None
        else None,
        "max_cost_usd": limits.max_cost_usd,
    }


def _add_tokens(state: RunState, usage: Mapping[str, int]) -> None:
    prompt, completion, total = _normalized_token_usage(usage)
    state.prompt_tokens += prompt
    state.completion_tokens += completion
    state.total_tokens += total


def _normalized_token_usage(usage: Mapping[str, int]) -> tuple[int, int, int]:
    prompt = _usage_counter(usage, "prompt_tokens")
    completion = _usage_counter(usage, "completion_tokens")
    total = max(_usage_counter(usage, "total_tokens"), prompt + completion)
    return prompt, completion, total


def _usage_counter(usage: Mapping[str, int], key: str) -> int:
    if key not in usage:
        return 0
    value = usage[key]
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ValueError("usage counter must be a non-negative integer")


def _state_for_stop_reason(reason: StopReason) -> AgentState:
    if reason.is_success:
        return AgentState.COMPLETED
    if reason is StopReason.NEEDS_HUMAN:
        return AgentState.NEEDS_HUMAN
    return AgentState.STOPPED


def _usage_snapshot(state: RunState) -> tuple[int, int, int, float]:
    return (
        state.prompt_tokens,
        state.completion_tokens,
        state.total_tokens,
        state.total_cost_usd,
    )


def _record_step_usage_delta(
    step: AgentStep,
    before: tuple[int, int, int, float],
    after: tuple[int, int, int, float],
) -> None:
    step.prompt_tokens += max(after[0] - before[0], 0)
    step.completion_tokens += max(after[1] - before[1], 0)
    step.total_tokens += max(after[2] - before[2], 0)
    step.estimated_cost_usd += max(after[3] - before[3], 0.0)


def _elapsed_ms(state: RunState, now_monotonic: float) -> float:
    elapsed = max(0.0, now_monotonic - state.started_at)
    return round(elapsed * 1000, 3)


def _close_step_duration(
    step: AgentStep, state: RunState, now_monotonic: float
) -> None:
    if step.duration_ms is not None:
        return
    started_at_ms = step.started_at_ms if step.started_at_ms is not None else 0.0
    duration = max(_elapsed_ms(state, now_monotonic) - started_at_ms, 0.0)
    step.duration_ms = round(duration, 3)


def _close_open_step_durations(
    steps: Sequence[AgentStep], state: RunState, now_monotonic: float
) -> None:
    for step in steps:
        _close_step_duration(step, state, now_monotonic)


def _cost_projection(state: RunState) -> tuple[str, float | None]:
    if state.saw_unpriced_cloud_usage:
        return "unknown", None
    if state.saw_priced_usage:
        return "estimated", round(state.total_cost_usd, 6)
    return "local_zero", 0.0


def _phase_trace(
    result: AgentRunResult, *, request: RunRequest
) -> list[dict[str, object]]:
    routes = result.trace.get("model_routes")
    route_items = (
        [item for item in routes if isinstance(item, dict)]
        if isinstance(routes, list)
        else []
    )
    return [
        _phase_projection(phase, result=result, request=request, routes=route_items)
        for phase in AgentPhase
    ]


def _phase_projection(
    phase: AgentPhase,
    *,
    result: AgentRunResult,
    request: RunRequest,
    routes: Sequence[dict[str, object]],
) -> dict[str, object]:
    phase_steps = _steps_for_phase(result.steps, phase)
    phase_routes = _routes_for_steps(routes, phase_steps)
    status, detail = _phase_status_detail(
        phase, result=result, request=request, steps=phase_steps
    )
    scenario_id = _scenario_id_from_request(request)
    projection: dict[str, object] = {
        "name": phase.value,
        "status": status.value,
        "detail": detail,
        "started_at": _phase_started_at(phase, phase_steps, status=status),
        "duration_ms": round(sum(step.duration_ms or 0.0 for step in phase_steps), 3),
        "step_ids": [step.step_index for step in phase_steps],
        "tool_call_ids": [
            f"step-{step.step_index}"
            for step in phase_steps
            if step.tool_name is not None
        ],
        "tool_names": sorted(
            {str(step.tool_name) for step in phase_steps if step.tool_name}
        ),
        "model_roles": [
            str(route["model_role"])
            for route in phase_routes
            if isinstance(route.get("model_role"), str)
        ],
        "provider_call_ids": [
            str(route["provider_call_id"])
            for route in phase_routes
            if isinstance(route.get("provider_call_id"), str)
        ],
        "usage": _phase_usage(phase_steps),
        "cost": _phase_cost(phase_steps, phase_routes),
    }
    if phase is AgentPhase.SCENARIO_SELECTION and scenario_id:
        projection["scenario_id"] = scenario_id
    if phase is AgentPhase.KNOWLEDGE_RETRIEVAL:
        projection["retrieval"] = _retrieval_summary(result, phase_steps)
    return projection


def _steps_for_phase(
    steps: Sequence[AgentStep], phase: AgentPhase
) -> list[AgentStep]:
    selected: list[AgentStep] = []
    for step in steps:
        step_phase = step.phase
        if step_phase is None:
            step_phase = phase_for_tool(step.tool_name)
        if step_phase is None and step.state is AgentState.COMPLETED:
            step_phase = AgentPhase.FINAL_VALIDATION
        if step_phase is phase:
            selected.append(step)
    return selected


def _routes_for_steps(
    routes: Sequence[dict[str, object]], steps: Sequence[AgentStep]
) -> list[dict[str, object]]:
    step_ids = {step.step_index for step in steps}
    return [
        route
        for route in routes
        if isinstance(route.get("step_id"), int) and route["step_id"] in step_ids
    ]


def _phase_status_detail(
    phase: AgentPhase,
    *,
    result: AgentRunResult,
    request: RunRequest,
    steps: Sequence[AgentStep],
) -> tuple[PhaseStatus, str]:
    if phase is AgentPhase.SCENARIO_SELECTION:
        if not result.trace.get("run_id"):
            return PhaseStatus.FAILED, "run_id_required"
        if _scenario_id_from_request(request):
            return PhaseStatus.COMPLETED, "scenario_selected"
        if _adapter_profile_from_request(request):
            return PhaseStatus.SKIPPED, "profile_without_scenario"
        return PhaseStatus.SKIPPED, "no_scenario_selector"
    if phase is AgentPhase.FINAL_VALIDATION:
        if result.stop_reason is StopReason.GUARDRAIL_TRIGGERED:
            return PhaseStatus.FAILED, "guardrail_triggered"
        if steps and any(step.error for step in steps):
            return PhaseStatus.FAILED, "planner_error"
        if steps:
            return PhaseStatus.COMPLETED, f"answer_{result.answer_status}"
        return PhaseStatus.SKIPPED, f"not_reached_{result.stop_reason.value}"
    if not steps:
        return PhaseStatus.SKIPPED, f"not_requested_{phase.value}"
    if any(step.error for step in steps):
        if any(step.tool_name for step in steps):
            return PhaseStatus.FAILED, "tool_error"
        return PhaseStatus.FAILED, "planner_error"
    if any(
        step.tool_result is not None and not step.tool_result.ok for step in steps
    ):
        return PhaseStatus.FAILED, "tool_error"
    if phase is AgentPhase.KNOWLEDGE_RETRIEVAL and not result.has_grounding_observation:
        return PhaseStatus.FAILED, "no_grounding_evidence"
    return PhaseStatus.COMPLETED, f"{phase.value}_completed"


def _phase_started_at(
    phase: AgentPhase, steps: Sequence[AgentStep], *, status: PhaseStatus
) -> str:
    if phase is AgentPhase.SCENARIO_SELECTION:
        return "request" if status is not PhaseStatus.SKIPPED else "not_started"
    if not steps:
        return "not_started"
    first = min(step.step_index for step in steps)
    return f"step-{first}"


def _phase_usage(steps: Sequence[AgentStep]) -> dict[str, object]:
    return {
        "prompt_tokens": sum(step.prompt_tokens for step in steps),
        "completion_tokens": sum(step.completion_tokens for step in steps),
        "total_tokens": sum(step.total_tokens for step in steps),
    }


def _phase_cost(
    steps: Sequence[AgentStep],
    routes: Sequence[dict[str, object]],
) -> dict[str, object]:
    cost = round(sum(step.estimated_cost_usd for step in steps), 6)
    if _has_unpriced_cloud_route(routes):
        return {"total_cost_usd": None, "cost_status": "unknown"}
    if cost > 0:
        return {"total_cost_usd": cost, "cost_status": "estimated"}
    if routes:
        return {"total_cost_usd": 0.0, "cost_status": "local_zero"}
    return {"total_cost_usd": 0.0, "cost_status": "local_zero"}


def _has_unpriced_cloud_route(routes: Sequence[dict[str, object]]) -> bool:
    return any(route.get("backend") != "local" for route in routes)


def _is_unpriced_cloud_request(request: RunRequest) -> bool:
    return _adapter_profile_from_request(request) == "live_provider"


def _adapter_profile_from_request(request: RunRequest) -> str:
    profile = request.query_options.get("adapter_profile")
    if isinstance(profile, str):
        return sanitize_identifier(profile, max_chars=80)
    return ""


def _scenario_id_from_request(request: RunRequest) -> str:
    scenario_id = request.query_options.get("scenario_id")
    if not isinstance(scenario_id, str):
        return ""
    stripped = scenario_id.strip()
    if not stripped or not _is_safe_public_identifier(stripped):
        return ""
    sanitized = sanitize_identifier(stripped, max_chars=80)
    if sanitized == "[REDACTED_IDENTIFIER]" or not sanitized.strip():
        return ""
    if not _is_safe_public_identifier(sanitized):
        return ""
    return sanitized


def _is_safe_public_identifier(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    first = value[0]
    if not (first.isascii() and first.isalnum()):
        return False
    allowed = set("._:-")
    for char in value:
        if char.isascii() and (char.isalnum() or char in allowed):
            continue
        return False
    return True


def _exception_token_usage(exc: BaseException) -> Mapping[str, int] | None:
    usage = getattr(exc, "safe_token_usage", None)
    if isinstance(usage, Mapping):
        return usage
    return None


def _exception_routing(exc: BaseException) -> tuple[PlannerRouting, ...]:
    routing = getattr(exc, "safe_routing", ())
    if not isinstance(routing, Sequence) or isinstance(routing, str | bytes):
        return ()
    return tuple(route for route in routing if isinstance(route, PlannerRouting))


def _exception_phase(exc: BaseException) -> AgentPhase | None:
    phase = getattr(exc, "safe_phase", None)
    if isinstance(phase, AgentPhase):
        return phase
    return None


def _retrieval_summary(
    result: AgentRunResult, steps: Sequence[AgentStep]
) -> dict[str, object]:
    hit_count = 0
    selected_chunk_count = 0
    source_count = 0
    for step in steps:
        tool_result = step.tool_result
        if tool_result is None:
            continue
        raw_hit_count = tool_result.meta.get("hit_count")
        if isinstance(raw_hit_count, int) and not isinstance(raw_hit_count, bool):
            hit_count += max(raw_hit_count, 0)
        selected = tool_result.meta.get("selected_chunk_ids")
        if isinstance(selected, list):
            selected_chunk_count += len(selected)
        sources = tool_result.meta.get("sources")
        if isinstance(sources, list):
            source_count += len(sources)
    return {
        "attempted": bool(steps),
        "hit_count": hit_count,
        "selected_chunk_count": selected_chunk_count,
        "source_count": source_count,
        "has_grounding_evidence": result.has_grounding_observation,
        "citation_present": result.has_grounding_source_citation,
    }


def _grounding_summary(result: AgentRunResult) -> dict[str, object]:
    return {
        "has_retrieval_evidence": result.has_grounding_observation,
        "has_source_citation": result.has_grounding_source_citation,
        "source_count": len(result.sources),
        "answer_status": result.answer_status,
    }
