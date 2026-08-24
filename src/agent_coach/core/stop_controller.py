"""Pure stop controller for Agent Core runs.

Provenance: behavior follows HomeTutor ``app.agent.stop_controller`` at
292be74f97b18615388838c2a1ddf2e0879585e0, without runtime settings or env
reads.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from agent_coach.core.contracts import RunLimits, StopDecision, StopReason


def compute_call_hash(tool_name: str, args: dict[str, Any]) -> str:
    """Stable hash of a tool call for duplicate detection."""

    blob = json.dumps(
        {"args": args, "tool": tool_name},
        default=str,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class RunState:
    """Mutable run accounting inspected by ``evaluate_stop``."""

    limits: RunLimits = field(default_factory=RunLimits)
    step_count: int = 0
    tool_call_hashes: list[str] = field(default_factory=list)
    consecutive_tool_errors: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0
    known_cost_usd: float = 0.0
    saw_priced_usage: bool = False
    saw_unpriced_cloud_usage: bool = False
    is_local_model: bool = False
    started_at: float = field(default_factory=time.monotonic)
    guardrail_triggered: bool = False
    invalid_args_after_repair: bool = False
    model_routes: list[dict[str, Any]] = field(default_factory=list)

    def record_tool_call(self, tool_name: str, args: dict[str, Any]) -> str:
        call_hash = compute_call_hash(tool_name, args)
        self.tool_call_hashes.append(call_hash)
        return call_hash

    def is_duplicate_call(self, tool_name: str, args: dict[str, Any]) -> bool:
        return compute_call_hash(tool_name, args) in self.tool_call_hashes

    def reset_tool_errors(self) -> None:
        self.consecutive_tool_errors = 0

    def increment_tool_error(self) -> None:
        self.consecutive_tool_errors += 1


def evaluate_stop(
    state: RunState,
    *,
    include_step_limit: bool = True,
    now_monotonic: float | None = None,
) -> StopDecision:
    """Inspect run state and return a terminal decision when a limit is hit."""

    limits = state.limits
    if state.guardrail_triggered:
        return StopDecision.halt(StopReason.GUARDRAIL_TRIGGERED)
    if state.invalid_args_after_repair:
        return StopDecision.halt(
            StopReason.INVALID_ARGS_AFTER_REPAIR,
            "tool args remained invalid after one repair attempt",
        )
    if include_step_limit and state.step_count >= limits.max_steps:
        return StopDecision.halt(
            StopReason.MAX_STEPS,
            f"step_count={state.step_count} >= max_steps={limits.max_steps}",
        )
    if limits.max_time_sec > 0:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        elapsed = now - state.started_at
        if elapsed > limits.max_time_sec:
            return StopDecision.halt(
                StopReason.MAX_TIME,
                f"elapsed={elapsed:.1f}s > max={limits.max_time_sec}s",
            )
    if (
        limits.max_tokens > 0
        and state.total_tokens > 0
        and state.total_tokens >= limits.max_tokens
    ):
        return StopDecision.halt(
            StopReason.MAX_TOKENS,
            f"tokens={state.total_tokens} >= max={limits.max_tokens}",
        )
    if (
        limits.max_cost_usd > 0
        and state.total_cost_usd > 0
        and state.total_cost_usd >= limits.max_cost_usd
    ):
        return StopDecision.halt(
            StopReason.MAX_COST,
            f"cost={state.total_cost_usd:.4f} >= max={limits.max_cost_usd}",
        )
    if state.consecutive_tool_errors >= limits.tool_error_limit:
        return StopDecision.halt(
            StopReason.TOOL_ERROR_LIMIT,
            f"consecutive_tool_errors={state.consecutive_tool_errors} "
            f">= limit={limits.tool_error_limit}",
        )
    return StopDecision.continue_run()
