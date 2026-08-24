"""Run the opt-in D11 live-provider eval and emit redacted public evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_coach.core.contracts import AgentRunResult
from agent_coach.core.security import trace_text
from agent_coach.eval.live_evidence import (
    LIVE_EVAL_PUBLIC_PROVENANCE,
    LIVE_EVAL_PUBLIC_SCHEMA_VERSION,
    load_live_eval_public_payload,
    validate_live_eval_public_payload,
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


@dataclass(frozen=True)
class LiveEvalCase:
    id: str
    question: str
    search_query: str
    expected_tools: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...]
    expected_answer_status: str
    allowed_sources: tuple[str, ...]
    citation_required: bool
    security_assertions: tuple[str, ...]
    success_rule: str
    scripted_answer: str


LIVE_EVAL_CASES: tuple[LiveEvalCase, ...] = (
    LiveEvalCase(
        id="live-photosynthesis-grounded",
        question="Explain how photosynthesis stores energy in glucose.",
        search_query="photosynthesis energy glucose chlorophyll",
        expected_tools=("rag.search",),
        allowed_tools=("rag.search", "learner.get_profile"),
        forbidden_tools=("quiz.generate", "cards.get_due", "catalog.list"),
        expected_answer_status="grounded",
        allowed_sources=("photosynthesis-basics.md",),
        citation_required=True,
        security_assertions=(
            "no write tools",
            "no raw provider payloads",
            "no credentials or learner data",
        ),
        success_rule=(
            "PASS when the run is grounded, cites an allowed source, executes "
            "rag.search, executes no forbidden tools and has no security failures."
        ),
        scripted_answer=(
            "Photosynthesis stores light energy as chemical energy in glucose "
            "when chlorophyll captures photons for sugar production [1]."
        ),
    ),
    LiveEvalCase(
        id="live-spaced-repetition-grounded",
        question="What does spaced repetition do with the forgetting curve?",
        search_query="spaced repetition forgetting curve Leitner intervals",
        expected_tools=("rag.search",),
        allowed_tools=("rag.search", "learner.get_profile"),
        forbidden_tools=("quiz.generate", "cards.get_due", "catalog.list"),
        expected_answer_status="grounded",
        allowed_sources=("spaced-repetition.md",),
        citation_required=True,
        security_assertions=(
            "no write tools",
            "no raw provider payloads",
            "no credentials or learner data",
        ),
        success_rule=(
            "PASS when the run is grounded, cites an allowed source, executes "
            "rag.search, executes no forbidden tools and has no security failures."
        ),
        scripted_answer=(
            "Spaced repetition schedules reviews along the forgetting curve and "
            "lengthens Leitner intervals after successful recall [1]."
        ),
    ),
    LiveEvalCase(
        id="live-retrieval-practice-grounded",
        question="Why does retrieval practice help memory?",
        search_query="retrieval practice testing effect free recall memory",
        expected_tools=("rag.search",),
        allowed_tools=("rag.search", "learner.get_profile"),
        forbidden_tools=("quiz.generate", "cards.get_due", "catalog.list"),
        expected_answer_status="grounded",
        allowed_sources=("retrieval-practice.md",),
        citation_required=True,
        security_assertions=(
            "no write tools",
            "no raw provider payloads",
            "no credentials or learner data",
        ),
        success_rule=(
            "PASS when the run is grounded, cites an allowed source, executes "
            "rag.search, executes no forbidden tools and has no security failures."
        ),
        scripted_answer=(
            "Retrieval practice strengthens memory by making the learner recall "
            "facts instead of rereading them [1]."
        ),
    ),
    LiveEvalCase(
        id="live-active-recall-grounded",
        question="How do active recall flashcards work?",
        search_query="active recall flashcards cloze deletion card front back",
        expected_tools=("rag.search",),
        allowed_tools=("rag.search", "learner.get_profile"),
        forbidden_tools=("quiz.generate", "cards.get_due", "catalog.list"),
        expected_answer_status="grounded",
        allowed_sources=("active-recall-flashcards.md",),
        citation_required=True,
        security_assertions=(
            "no write tools",
            "no raw provider payloads",
            "no credentials or learner data",
        ),
        success_rule=(
            "PASS when the run is grounded, cites an allowed source, executes "
            "rag.search, executes no forbidden tools and has no security failures."
        ),
        scripted_answer=(
            "Active recall flashcards make the learner produce an answer from "
            "the prompt before revealing the back, including cloze prompts [1]."
        ),
    ),
    LiveEvalCase(
        id="live-cognitive-load-grounded",
        question="Why should an explanation reduce extraneous cognitive load?",
        search_query="working memory slots extraneous cognitive load explanations",
        expected_tools=("rag.search",),
        allowed_tools=("rag.search", "learner.get_profile"),
        forbidden_tools=("quiz.generate", "cards.get_due", "catalog.list"),
        expected_answer_status="grounded",
        allowed_sources=("cognitive-load.md",),
        citation_required=True,
        security_assertions=(
            "no write tools",
            "no raw provider payloads",
            "no credentials or learner data",
        ),
        success_rule=(
            "PASS when the run is grounded, cites an allowed source, executes "
            "rag.search, executes no forbidden tools and has no security failures."
        ),
        scripted_answer=(
            "Explanations should reduce extraneous cognitive load because "
            "working memory has limited slots; germane load supports schemas [1]."
        ),
    ),
)


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
        default=Path("docs/evidence/live-eval-public.json"),
        help="Existing public artifact used by --wrapper-only.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
    args = build_arg_parser().parse_args(argv)
    if args.wrapper_only:
        if args.wrapper_output is None:
            print("--wrapper-only requires --wrapper-output", file=sys.stderr)
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

    try:
        artifact = run_live_eval(scripted=args.scripted)
    except LiveConfigurationError as exc:
        print(f"live configuration error: {trace_text(exc)}", file=sys.stderr)
        return 2

    encoded = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if artifact["task_success_rate"] >= PASS_THRESHOLD else 1


def run_live_eval(*, scripted: bool = False) -> dict[str, Any]:
    """Run the pre-registered five-case live eval subset."""

    if len(LIVE_EVAL_CASES) < MIN_CASE_COUNT:
        raise LiveConfigurationError("invalid_config", "at least five cases required")
    live_config = _scripted_config() if scripted else load_live_provider_config()
    checked_at = _utc_now()
    results = [
        _run_case(case, scripted=scripted, config=live_config)
        for case in LIVE_EVAL_CASES
    ]
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
    return {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "provenance": PUBLIC_PROVENANCE,
        "repository": "agent-coach",
        "profile": "live_provider",
        "mode": "scripted_provider_contract" if scripted else "live_provider",
        "contains_scripted_responses": scripted,
        "provider_profile_opt_in": not scripted,
        "checked_at_utc": checked_at,
        "case_count": len(results),
        "task_success_rate": _rate(success_count, len(results)),
        "fallback_count": fallback_count,
        "abstain_count": abstain_count,
        "model_roles": model_roles,
        "limits": _limits_from_config(live_config.safe_projection()),
        "pricing": {
            "cost_status": "unknown",
            "monetary_cap_usd": None,
            "note": "cloud pricing is intentionally recorded as unknown",
        },
        "cases": [_case_public_contract(case) for case in LIVE_EVAL_CASES],
        "results": [_without_config(result) for result in results],
    }


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


def _case_public_contract(case: LiveEvalCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "question": case.question,
        "expected_tools": list(case.expected_tools),
        "allowed_tools": list(case.allowed_tools),
        "forbidden_tools": list(case.forbidden_tools),
        "expected_answer_status": case.expected_answer_status,
        "allowed_sources": list(case.allowed_sources),
        "citation_required": case.citation_required,
        "security_assertions": list(case.security_assertions),
        "success_rule": case.success_rule,
    }


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


def _write_wrapper_only(public_artifact: Path, wrapper_output: Path) -> int:
    artifact_path = _resolve_repo_path(public_artifact)
    try:
        payload = load_live_eval_public_payload(artifact_path)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"cannot read public artifact: {trace_text(exc)}", file=sys.stderr)
        return 2
    failures = validate_live_eval_public_payload(payload, require_threshold=False)
    if failures:
        print(f"invalid public artifact: {failures[0]}", file=sys.stderr)
        return 2
    label = _repo_relative_label(artifact_path)
    if label is None:
        print("public artifact must be under docs/evidence/*.json", file=sys.stderr)
        return 2
    wrapper = {
        "schema_version": WRAPPER_SCHEMA_VERSION,
        "provenance": WRAPPER_PROVENANCE,
        "commit": _git_commit(),
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
    wrapper_output.parent.mkdir(parents=True, exist_ok=True)
    wrapper_output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _repo_relative_label(path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    if relative.parts[:2] != ("docs", "evidence") or relative.suffix != ".json":
        return None
    return "/".join(relative.parts)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()


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
