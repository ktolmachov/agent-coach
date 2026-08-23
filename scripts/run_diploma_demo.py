"""Run the deterministic diploma demo and emit review evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent_coach.core.contracts import AgentRunResult, AgentStep
from agent_coach.mock import build_mock_composition

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SCHEMA_VERSION = "agent-coach-diploma-evidence/1.0.0"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic offline Agent Coach diploma scenario.",
    )
    parser.add_argument(
        "--scenario",
        default="grounded_success",
        help="Synthetic scenario id from fixtures/mock_scenarios.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON evidence path to write.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        composition = build_mock_composition(args.scenario)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2

    result = composition.runner.run(composition.request)
    evidence = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "repository": "agent-coach",
        "commit": _git_commit(),
        "worktree_dirty": _git_worktree_dirty(),
        "adapter_profile": "mock",
        "scenario_id": args.scenario,
        "mock_api": {
            "bind": "127.0.0.1:8008",
            "swagger_url": "http://127.0.0.1:8008/docs",
            "production_auth": False,
            "state_store": "ephemeral_in_memory",
        },
        "contracts": {
            "schema_version": "agent-contracts/1.0.0",
            "schema_hash": (
                "218c90732c25ae2f9b26c4f5a9ea5ee81c28bf797299c99b53e310bf22315910"
            ),
        },
        "tools": [tool.name for tool in composition.tools],
        "result": _result_projection(result),
        "store_events": [event["event"] for event in composition.store.events],
        "limitations": [
            "standalone deterministic diploma demo",
            "no production authentication",
            "no production data",
            "no durable production state",
            "no production deployment approval",
        ],
    }
    encoded = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


def _result_projection(result: AgentRunResult) -> dict[str, Any]:
    tool_calls = result.trace.get("tool_calls", [])
    return {
        "answer_status": result.answer_status,
        "state": result.state.value,
        "stop_reason": result.stop_reason.value,
        "success": result.success,
        "source_count": len(result.sources),
        "tool_call_count": len(tool_calls) if isinstance(tool_calls, list) else 0,
        "tool_calls": tool_calls,
        "phases": result.trace.get("phases", []),
        "steps": [_step_projection(step) for step in result.steps],
    }


def _step_projection(step: AgentStep) -> dict[str, Any]:
    return {
        "step_index": step.step_index,
        "state": step.state.value,
        "tool_name": step.tool_name,
        "tool_ok": step.tool_result.ok if step.tool_result is not None else None,
        "tool_error": step.tool_result.error if step.tool_result is not None else None,
        "error": step.error,
    }


def _git_commit() -> str:
    try:
        return _git_output("rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_worktree_dirty() -> bool:
    try:
        return bool(_git_output("status", "--short"))
    except (OSError, subprocess.CalledProcessError):
        return True


def _git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO_ROOT,
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
