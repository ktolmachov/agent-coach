"""Run the opt-in D11 live-provider eval and emit redacted public evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_coach.core.contracts import AgentRunResult
from agent_coach.core.security import trace_text
from agent_coach.eval.live_evidence import (
    AUTONOMOUS_LIVE_EVAL_CASE_REGISTRY,
    AUTONOMOUS_LIVE_EVAL_PUBLIC_PROVENANCE,
    AUTONOMOUS_LIVE_EVAL_PUBLIC_SCHEMA_VERSION,
    AUTONOMOUS_LIVE_EVAL_THRESHOLDS,
    AUTONOMOUS_LIVE_POLICY,
    LIVE_EVAL_CASES,
    LIVE_EVAL_PUBLIC_PROVENANCE,
    LIVE_EVAL_PUBLIC_SCHEMA_VERSION,
    LIVE_EXECUTION_BACKEND,
    SCRIPTED_EXECUTION_BACKEND,
    AutonomousLiveEvalCase,
    LiveEvalCase,
    autonomous_live_eval_case_registry_hash,
    autonomous_live_eval_metrics,
    bounded_live_eval_failure,
    is_historical_live_eval_path,
    is_historical_live_eval_payload,
    live_eval_case_registry_hash,
    live_eval_contract_hash,
    live_eval_corpus_hash,
    load_live_eval_public_payload,
    public_autonomous_case_contract,
    public_case_contract,
    validate_autonomous_live_eval_public_payload,
    validate_current_live_eval_public_payload,
)
from agent_coach.profiles.live import build_live_composition
from agent_coach.provider.config import (
    LiveProviderConfig,
    ModelRoleSettings,
    load_live_provider_config,
)
from agent_coach.provider.errors import LiveConfigurationError, ProviderAdapterError
from agent_coach.provider.model_router import PLANNER_ROLE, SYNTHESIZER_ROLE
from agent_coach.provider.openai_responses import (
    NormalizedFunctionCall,
    NormalizedResponse,
    PlannerToolRequirement,
    ScriptedResponsesClient,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SCHEMA_VERSION = LIVE_EVAL_PUBLIC_SCHEMA_VERSION
WRAPPER_SCHEMA_VERSION = "agent-coach-live-eval-evidence/1.0.0"
PUBLIC_PROVENANCE = LIVE_EVAL_PUBLIC_PROVENANCE
WRAPPER_PROVENANCE = {
    "classification": "redacted_live_provider_eval",
    "contains_credentials": False,
    "contains_learner_data": False,
    "contains_hometutor_runtime_dependency": False,
}
MIN_CASE_COUNT = 5
PASS_THRESHOLD = 0.8


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the opt-in D11 live-provider eval.",
    )
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="Use a scripted Responses client for offline runner validation.",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Run the separate autonomous tool-selection eval.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Acknowledge that live mode may call the provider network.",
    )
    parser.add_argument(
        "--provider-opt-in",
        action="store_true",
        help="Acknowledge use of provider credentials from the environment.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional public redacted artifact path.",
    )
    parser.add_argument(
        "--wrapper-output",
        type=Path,
        help="Optional external live evidence wrapper path.",
    )
    parser.add_argument(
        "--wrapper-only",
        action="store_true",
        help="Write only the external wrapper for an existing public artifact.",
    )
    parser.add_argument(
        "--public-artifact",
        type=Path,
        help="Existing public artifact used by --wrapper-only.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
    args = build_arg_parser().parse_args(argv)
    if args.wrapper_only:
        if args.autonomous:
            print("--wrapper-only is only for forced live evidence", file=sys.stderr)
            return 2
        if args.wrapper_output is None or args.public_artifact is None:
            print(
                "--wrapper-only requires --public-artifact and --wrapper-output",
                file=sys.stderr,
            )
            return 2
        return _write_wrapper_only(args.public_artifact, args.wrapper_output)
    if args.scripted and args.wrapper_output is not None:
        print("scripted Responses validation is not live evidence", file=sys.stderr)
        return 2
    if not args.scripted and not (args.allow_network and args.provider_opt_in):
        print(
            "live eval requires --allow-network and --provider-opt-in",
            file=sys.stderr,
        )
        return 2
    output_path = None if args.output is None else _absolute_repo_path(args.output)
    if (
        not args.scripted
        and output_path is not None
        and _output_is_inside_checkout(output_path)
    ):
        print(
            "current live evidence must be written outside the checkout",
            file=sys.stderr,
        )
        return 2

    try:
        artifact = (
            run_autonomous_live_eval(scripted=args.scripted)
            if args.autonomous
            else run_live_eval(scripted=args.scripted)
        )
    except LiveConfigurationError as exc:
        print(f"live configuration error: {trace_text(exc)}", file=sys.stderr)
        return 2
    if not args.scripted:
        evaluated_commit, clean_worktree = _git_provenance()
        artifact["evaluated_commit"] = evaluated_commit
        artifact["clean_worktree"] = clean_worktree
        if evaluated_commit is None or clean_worktree is not True:
            print("current live evidence requires a clean worktree", file=sys.stderr)
            return 2

    encoded = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if output_path is not None and not _publish_evidence_file(
        output_path, encoded, require_clean=not args.scripted
    ):
        print("current live evidence requires a clean worktree", file=sys.stderr)
        return 2
    print(encoded, end="")
    if args.autonomous:
        failures = validate_autonomous_live_eval_public_payload(
            artifact,
            allow_scripted=args.scripted,
        )
        return 0 if not failures else 1
    return 0 if artifact["task_success_rate"] >= PASS_THRESHOLD else 1


def run_live_eval(*, scripted: bool = False) -> dict[str, Any]:
    """Run the pre-registered five-case live eval subset."""

    if len(LIVE_EVAL_CASES) < MIN_CASE_COUNT:
        raise LiveConfigurationError("invalid_config", "at least five cases required")
    live_config = _scripted_config() if scripted else load_live_provider_config()
    results = [
        _run_case(case, scripted=scripted, config=live_config)
        for case in LIVE_EVAL_CASES
    ]
    evaluated_commit, clean_worktree = _git_provenance()
    checked_at = _utc_now()
    success_count = sum(1 for result in results if result["task_success"] is True)
    fallback_count = sum(1 for result in results if result["answer_fallback"] is True)
    abstain_count = sum(1 for result in results if result["answer_status"] == "abstain")
    model_roles = sorted(
        {
            role
            for result in results
            for role in result.get("model_roles", [])
            if isinstance(role, str)
        }
    )
    safe_config = live_config.safe_projection()
    return {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "provenance": PUBLIC_PROVENANCE,
        "repository": "agent-coach",
        "profile": "live_provider",
        "mode": "scripted_provider_contract" if scripted else "live_provider",
        "contains_scripted_responses": scripted,
        "provider_profile_opt_in": not scripted,
        "execution_backend": (
            SCRIPTED_EXECUTION_BACKEND if scripted else LIVE_EXECUTION_BACKEND
        ),
        "evaluated_commit": evaluated_commit,
        "clean_worktree": clean_worktree,
        "contract_hash": live_eval_contract_hash(),
        "corpus_hash": live_eval_corpus_hash(),
        "case_registry_hash": live_eval_case_registry_hash(),
        "model_projection": {
            "planner": safe_config.get("planner"),
            "synthesizer": safe_config.get("synthesizer"),
        },
        "checked_at_utc": checked_at,
        "case_count": len(results),
        "task_success_rate": _rate(success_count, len(results)),
        "fallback_count": fallback_count,
        "abstain_count": abstain_count,
        "model_roles": model_roles,
        "limits": _limits_from_config(safe_config),
        "pricing": {
            "cost_status": "unknown",
            "monetary_cap_usd": None,
            "note": "cloud pricing is intentionally recorded as unknown",
        },
        "cases": [public_case_contract(case) for case in LIVE_EVAL_CASES],
        "results": [_without_config(result) for result in results],
    }


def run_autonomous_live_eval(*, scripted: bool = False) -> dict[str, Any]:
    """Run the autonomous tool-selection eval harness."""

    live_config = _scripted_config() if scripted else load_live_provider_config()
    results = [
        _run_autonomous_case(case, scripted=scripted, config=live_config)
        for case in AUTONOMOUS_LIVE_EVAL_CASE_REGISTRY
    ]
    evaluated_commit, clean_worktree = _git_provenance()
    metrics = _autonomous_metrics(results)
    return {
        "schema_version": AUTONOMOUS_LIVE_EVAL_PUBLIC_SCHEMA_VERSION,
        "provenance": AUTONOMOUS_LIVE_EVAL_PUBLIC_PROVENANCE,
        "repository": "agent-coach",
        "profile": "live_provider",
        "mode": "scripted_provider_contract" if scripted else "live_provider",
        "contains_scripted_responses": scripted,
        "provider_profile_opt_in": not scripted,
        "execution_backend": (
            SCRIPTED_EXECUTION_BACKEND if scripted else LIVE_EXECUTION_BACKEND
        ),
        "evaluated_commit": evaluated_commit,
        "clean_worktree": clean_worktree,
        "contract_hash": live_eval_contract_hash(),
        "corpus_hash": live_eval_corpus_hash(),
        "case_registry_hash": autonomous_live_eval_case_registry_hash(),
        "checked_at_utc": _utc_now(),
        "case_count": len(results),
        "policy": AUTONOMOUS_LIVE_POLICY,
        "thresholds": AUTONOMOUS_LIVE_EVAL_THRESHOLDS,
        "metrics": metrics,
        "cases": [
            public_autonomous_case_contract(case)
            for case in AUTONOMOUS_LIVE_EVAL_CASE_REGISTRY
        ],
        "results": results,
    }


def _run_autonomous_case(
    case: AutonomousLiveEvalCase, *, scripted: bool, config: LiveProviderConfig
) -> dict[str, Any]:
    client = _autonomous_scripted_client(case) if scripted else None
    try:
        composition = build_live_composition(
            case.question,
            config=config,
            client=client,
            run_id=f"autonomous-live-eval-{case.id}",
        )
        result = composition.runner.run(composition.request)
    except (LiveConfigurationError, ProviderAdapterError) as exc:
        return _autonomous_failure_projection(case, exc)
    return _autonomous_result_projection(case, result)


def _run_case(
    case: LiveEvalCase, *, scripted: bool, config: LiveProviderConfig
) -> dict[str, Any]:
    client = _scripted_client(case) if scripted else None
    try:
        composition = build_live_composition(
            case.question,
            config=config,
            client=client,
            run_id=f"live-eval-{case.id}",
            tool_requirement=PlannerToolRequirement(
                name="rag.search",
                arguments={"query": case.search_query, "top_k": 2},
            ),
        )
        result = composition.runner.run(composition.request)
    except (LiveConfigurationError, ProviderAdapterError) as exc:
        return _failure_projection(case, exc)
    projection = _result_projection(case, result)
    projection["config"] = composition.config.safe_projection()
    return projection


def _failure_projection(case: LiveEvalCase, exc: Exception) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "task_success": False,
        "error": trace_text(exc),
        "answer_status": "abstain",
        "answer_fallback": True,
        "stop_reason": _provider_error_code(exc),
        "state": "stopped",
        "tool_calls": [],
        "sources": [],
        "phase_statuses": [],
        "model_roles": [],
        "tokens": {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        },
        "duration_ms": 0.0,
        "cost_status": "unknown",
        "total_cost_usd": None,
        "grounding": {
            "answer_status": "abstain",
            "has_retrieval_evidence": False,
            "has_source_citation": False,
            "source_count": 0,
        },
        "security": {
            "security_failures": 0,
            "hidden_writes": 0,
            "forbidden_tool_executions": [],
        },
        "config": {},
    }


def _provider_error_code(exc: Exception) -> str:
    code = getattr(exc, "category", None) or getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    return "provider_error"


def _result_projection(case: LiveEvalCase, result: AgentRunResult) -> dict[str, Any]:
    tool_calls = [
        step.tool_name for step in result.steps if isinstance(step.tool_name, str)
    ]
    sources = [_source_projection(source) for source in result.sources]
    model_routes = result.trace.get("model_routes")
    routes = [item for item in model_routes if isinstance(item, dict)] if (
        isinstance(model_routes, list)
    ) else []
    security_failures = _security_failure_count(result)
    hidden_writes = len([name for name in tool_calls if name not in case.allowed_tools])
    task_success = (
        result.answer_status == case.expected_answer_status
        and all(tool in tool_calls for tool in case.expected_tools)
        and not any(tool in tool_calls for tool in case.forbidden_tools)
        and hidden_writes == 0
        and security_failures == 0
        and (
            not case.citation_required
            or result.has_grounding_source_citation
        )
        and _has_allowed_source(sources, case.allowed_sources)
    )
    return {
        "case_id": case.id,
        "task_success": task_success,
        "answer_status": result.answer_status,
        "answer_fallback": result.answer_fallback,
        "stop_reason": result.stop_reason.value,
        "state": result.state.value,
        "tool_calls": tool_calls,
        "sources": sources,
        "phase_statuses": _phase_statuses(result),
        "model_roles": [
            str(route["model_role"])
            for route in routes
            if isinstance(route.get("model_role"), str)
        ],
        "tokens": {
            "prompt_tokens": result.trace.get("prompt_tokens"),
            "completion_tokens": result.trace.get("completion_tokens"),
            "total_tokens": result.trace.get("total_tokens"),
        },
        "duration_ms": result.trace.get("duration_ms"),
        "cost_status": result.trace.get("cost_status"),
        "total_cost_usd": result.trace.get("total_cost_usd"),
        "grounding": result.trace.get("grounding"),
        "security": {
            "security_failures": security_failures,
            "hidden_writes": hidden_writes,
            "forbidden_tool_executions": [
                name for name in tool_calls if name in case.forbidden_tools
            ],
        },
    }


def _autonomous_result_projection(
    case: AutonomousLiveEvalCase,
    result: AgentRunResult,
) -> dict[str, Any]:
    tool_calls = [
        {
            "name": str(step.tool_name),
            "args": dict(step.tool_args),
            "executed": step.tool_result is not None,
            "error": step.error,
        }
        for step in result.steps
        if isinstance(step.tool_name, str)
    ]
    names = [call["name"] for call in tool_calls]
    executed_names = [call["name"] for call in tool_calls if call["executed"] is True]
    expected_tool = case.expected_tool
    if expected_tool is None:
        tool_name_ok = not names
        args_ok = True
    else:
        tool_name_ok = names == [expected_tool]
        args_ok = bool(tool_calls) and tool_calls[0]["args"] == dict(
            case.expected_args
        )
    invalid_executions = sum(1 for call in tool_calls if call["error"])
    forbidden_executions = [
        name for name in executed_names if name in case.forbidden_tools
    ]
    task_success = (
        tool_name_ok
        and args_ok
        and invalid_executions == 0
        and not forbidden_executions
    )
    if case.group == "insufficient_malformed_arguments":
        task_success = (
            result.stop_reason.value == "invalid_decision"
            and bool(tool_calls)
            and not executed_names
        )
        invalid_executions = 0
    return {
        "case_id": case.id,
        "group": case.group,
        "task_success": task_success,
        "answer_status": result.answer_status,
        "stop_reason": result.stop_reason.value,
        "state": result.state.value,
        "tool_calls": tool_calls,
        "invalid_executions": invalid_executions,
        "forbidden_tool_executions": forbidden_executions,
    }


def _autonomous_failure_projection(
    case: AutonomousLiveEvalCase,
    exc: Exception,
) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "group": case.group,
        "task_success": False,
        "error": trace_text(exc),
        "answer_status": "abstain",
        "stop_reason": _provider_error_code(exc),
        "state": "stopped",
        "tool_calls": [],
        "invalid_executions": 0,
        "forbidden_tool_executions": [],
    }


def _autonomous_metrics(results: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    return autonomous_live_eval_metrics(results)


def _source_projection(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: source[key]
        for key in ("file_name", "title", "url", "cite_index")
        if key in source
    }


def _phase_statuses(result: AgentRunResult) -> list[dict[str, str]]:
    phases = result.trace.get("phases")
    if not isinstance(phases, list):
        return []
    return [
        {
            "name": str(phase.get("name") or ""),
            "status": str(phase.get("status") or ""),
            "detail": str(phase.get("detail") or ""),
        }
        for phase in phases
        if isinstance(phase, dict)
    ]


def _security_failure_count(result: AgentRunResult) -> int:
    encoded = json.dumps(_safe_result_for_scan(result), ensure_ascii=False)
    unsafe_markers = (
        "api_key",
        "bearer ",
        "password=",
        "secret=",
        "sk-proj-",
        "learner@example",
        "system prompt",
    )
    normalized = encoded.casefold()
    return sum(1 for marker in unsafe_markers if marker in normalized)


def _safe_result_for_scan(result: AgentRunResult) -> dict[str, Any]:
    return {
        "answer": result.answer,
        "sources": result.sources,
        "trace": result.trace,
        "steps": [
            {
                "tool_name": step.tool_name,
                "tool_args": step.tool_args,
                "tool_error": step.error,
            }
            for step in result.steps
        ],
    }


def _has_allowed_source(
    sources: Sequence[Mapping[str, Any]], allowed_sources: Sequence[str]
) -> bool:
    allowed = set(allowed_sources)
    for source in sources:
        for key in ("file_name", "title", "url"):
            value = source.get(key)
            if isinstance(value, str) and value in allowed:
                return True
    return False


def _limits_from_config(config: object) -> dict[str, object]:
    if not isinstance(config, Mapping):
        return {}
    return {
        "timeout_sec": config.get("timeout_sec"),
        "max_retries": config.get("max_retries"),
        "max_output_tokens": config.get("max_output_tokens"),
        "max_question_chars": config.get("max_question_chars"),
        "max_run_tokens": config.get("max_run_tokens"),
        "run_time_limit_sec": config.get("run_time_limit_sec"),
        "cost_cap_usd": config.get("cost_cap_usd"),
        "routing_status": config.get("routing_status"),
    }


def _without_config(result: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "config"}


def _scripted_config() -> LiveProviderConfig:
    return LiveProviderConfig(
        api_key="scripted-key",
        planner=ModelRoleSettings(role=PLANNER_ROLE, model_id="scripted-planner"),
        synthesizer=ModelRoleSettings(
            role=SYNTHESIZER_ROLE, model_id="scripted-synthesizer"
        ),
    )


def _scripted_client(case: LiveEvalCase) -> ScriptedResponsesClient:
    call_id = f"{case.id}-call"
    return ScriptedResponsesClient(
        [
            NormalizedResponse(
                response_id=f"{case.id}-planner",
                status="completed",
                function_calls=(
                    NormalizedFunctionCall(
                        call_id=call_id,
                        name="rag.search",
                        arguments_json=json.dumps(
                            {"query": case.search_query, "top_k": 2},
                            sort_keys=True,
                        ),
                    ),
                ),
                prompt_tokens=12,
                completion_tokens=4,
                total_tokens=16,
            ),
            NormalizedResponse(
                response_id=f"{case.id}-synthesizer",
                status="completed",
                output_text=case.scripted_answer,
                prompt_tokens=10,
                completion_tokens=14,
                total_tokens=24,
            ),
        ]
    )


def _autonomous_scripted_client(
    case: AutonomousLiveEvalCase,
) -> ScriptedResponsesClient:
    if case.scripted_tool_name is None:
        return ScriptedResponsesClient(
            [
                NormalizedResponse(
                    response_id=f"{case.id}-planner",
                    status="completed",
                    output_text=case.scripted_answer,
                    prompt_tokens=8,
                    completion_tokens=6,
                    total_tokens=14,
                ),
            ]
        )
    return ScriptedResponsesClient(
        [
            NormalizedResponse(
                response_id=f"{case.id}-planner",
                status="completed",
                function_calls=(
                    NormalizedFunctionCall(
                        call_id=f"{case.id}-call",
                        name=case.scripted_tool_name,
                        arguments_json=json.dumps(case.scripted_args, sort_keys=True),
                    ),
                ),
                prompt_tokens=10,
                completion_tokens=4,
                total_tokens=14,
            ),
            NormalizedResponse(
                response_id=f"{case.id}-synthesizer",
                status="completed",
                output_text=case.scripted_answer,
                prompt_tokens=8,
                completion_tokens=8,
                total_tokens=16,
            ),
        ]
    )


def _write_wrapper_only(public_artifact: Path, wrapper_output: Path) -> int:
    artifact_path = _absolute_repo_path(public_artifact)
    wrapper_path = _absolute_repo_path(wrapper_output)
    label = _public_artifact_label(artifact_path)
    if label is not None and is_historical_live_eval_path(label):
        print("historical example is not current live evidence", file=sys.stderr)
        return 2
    if _output_is_inside_checkout(artifact_path) or _output_is_inside_checkout(
        wrapper_path
    ):
        print(
            "current live evidence must be written outside the checkout",
            file=sys.stderr,
        )
        return 2
    if label is None:
        print("public artifact path is not an allowed live JSON file", file=sys.stderr)
        return 2
    try:
        payload = load_live_eval_public_payload(artifact_path)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        detail = bounded_live_eval_failure((trace_text(exc),))
        print(f"cannot read public artifact: {detail}", file=sys.stderr)
        return 2
    if is_historical_live_eval_payload(payload):
        print("historical example is not current live evidence", file=sys.stderr)
        return 2
    try:
        expected_commit = _git_commit()
    except (OSError, subprocess.CalledProcessError, subprocess.SubprocessError):
        expected_commit = None
    failures = validate_current_live_eval_public_payload(
        payload,
        require_threshold=False,
        expected_commit=expected_commit,
        path=label,
    )
    if expected_commit is None:
        failures.append("live eval evaluated_commit does not match expected commit")
    try:
        worktree_clean = _git_worktree_clean()
    except (OSError, subprocess.CalledProcessError, subprocess.SubprocessError):
        worktree_clean = False
    if worktree_clean is not True:
        failures.append("current live evidence requires a clean worktree")
    if failures:
        print(
            f"invalid public artifact: {bounded_live_eval_failure(failures)}",
            file=sys.stderr,
        )
        return 2
    wrapper = {
        "schema_version": WRAPPER_SCHEMA_VERSION,
        "provenance": WRAPPER_PROVENANCE,
        "commit": payload.get("evaluated_commit"),
        "profile": "live_provider",
        "provider_profile_opt_in": True,
        "checked_at_utc": _utc_now(),
        "case_count": payload.get("case_count"),
        "task_success_rate": payload.get("task_success_rate"),
        "evidence_artifacts": [
            {
                "label": label,
                "sha256": _sha256_file(artifact_path),
            }
        ],
    }
    encoded = json.dumps(wrapper, indent=2, sort_keys=True) + "\n"
    if not _publish_evidence_file(wrapper_path, encoded, require_clean=True):
        print("current live evidence requires a clean worktree", file=sys.stderr)
        return 2
    print(encoded, end="")
    return 0


def _publish_evidence_file(
    path: Path, encoded: str, *, require_clean: bool
) -> bool:
    path = _absolute_repo_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.partial")
    published = False
    try:
        partial.write_text(encoded, encoding="utf-8")
        if require_clean:
            try:
                still_clean = _git_worktree_clean()
            except (
                OSError,
                subprocess.CalledProcessError,
                subprocess.SubprocessError,
            ):
                still_clean = False
            if still_clean is not True:
                return False
        partial.replace(path)
        published = True
    finally:
        if not published:
            partial.unlink(missing_ok=True)
    return published


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _absolute_repo_path(path: Path) -> Path:
    return _resolve_repo_path(path).resolve()


def _output_is_inside_checkout(path: Path) -> bool:
    try:
        _absolute_repo_path(path).relative_to(REPO_ROOT.resolve())
    except ValueError:
        return False
    return True


def _public_artifact_label(path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        if path.suffix != ".json" or not path.name or "/" in path.name:
            return None
        return path.name
    if relative.suffix != ".json" or relative.is_absolute() or ".." in relative.parts:
        return None
    label = "/".join(relative.parts)
    if is_historical_live_eval_path(label):
        return label
    return None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()


def _git_worktree_clean() -> bool:
    output = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return output.strip() == ""


def _git_provenance() -> tuple[str | None, bool]:
    try:
        commit = _git_commit()
    except (OSError, subprocess.CalledProcessError):
        return None, False
    if not commit:
        return None, False
    try:
        clean = _git_worktree_clean()
    except (OSError, subprocess.CalledProcessError):
        return commit, False
    return commit, clean


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
