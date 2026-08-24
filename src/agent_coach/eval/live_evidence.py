"""Validation helpers for redacted D11 live-provider public evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LIVE_EVAL_PUBLIC_SCHEMA_VERSION = "agent-coach-live-eval-public/1.0.0"
LIVE_EVAL_PUBLIC_PROVENANCE = {
    "classification": "redacted_live_provider_eval_public",
    "contains_credentials": False,
    "contains_learner_data": False,
    "contains_hometutor_runtime_dependency": False,
    "contains_raw_provider_payloads": False,
}
LIVE_EVAL_MIN_TASK_SUCCESS_RATE = 0.8
MAX_LIVE_EVIDENCE_JSON_BYTES = 64_000


@dataclass(frozen=True)
class LiveEvalCaseContract:
    id: str
    question: str
    expected_tools: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...]
    expected_answer_status: str
    allowed_sources: tuple[str, ...]
    citation_required: bool
    security_assertions: tuple[str, ...]
    success_rule: str


LIVE_EVAL_CASE_REGISTRY: tuple[LiveEvalCaseContract, ...] = (
    LiveEvalCaseContract(
        id="live-photosynthesis-grounded",
        question="Explain how photosynthesis stores energy in glucose.",
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
    ),
    LiveEvalCaseContract(
        id="live-spaced-repetition-grounded",
        question="What does spaced repetition do with the forgetting curve?",
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
    ),
    LiveEvalCaseContract(
        id="live-retrieval-practice-grounded",
        question="Why does retrieval practice help memory?",
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
    ),
    LiveEvalCaseContract(
        id="live-active-recall-grounded",
        question="How do active recall flashcards work?",
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
    ),
    LiveEvalCaseContract(
        id="live-cognitive-load-grounded",
        question="Why should an explanation reduce extraneous cognitive load?",
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
    ),
)


def validate_live_eval_public_payload(
    payload: object, *, require_threshold: bool = True
) -> list[str]:
    """Return validation failures for the committed redacted live artifact."""

    if not isinstance(payload, Mapping):
        return ["live eval public evidence must be a JSON object"]
    failures: list[str] = []
    if payload.get("schema_version") != LIVE_EVAL_PUBLIC_SCHEMA_VERSION:
        failures.append("public artifact schema is not live eval public evidence")
    if payload.get("provenance") != LIVE_EVAL_PUBLIC_PROVENANCE:
        failures.append("unexpected live eval provenance")
    if payload.get("repository") != "agent-coach":
        failures.append("live eval evidence must identify the agent-coach repository")
    if payload.get("profile") != "live_provider":
        failures.append("live eval evidence must use live_provider")
    if payload.get("contains_scripted_responses") is not False:
        failures.append("scripted responses are not live evidence")
    if payload.get("mode") != "live_provider":
        failures.append("live eval evidence mode must be live_provider")
    if payload.get("provider_profile_opt_in") is not True:
        failures.append("live eval evidence lacks provider opt-in marker")
    failures.extend(_validate_registered_cases(payload.get("cases")))
    case_count = payload.get("case_count")
    expected_case_count = len(LIVE_EVAL_CASE_REGISTRY)
    if case_count != expected_case_count or isinstance(case_count, bool):
        failures.append("live eval evidence must include the registered live cases")
    success_rate = _bounded_rate_value(payload.get("task_success_rate"))
    if success_rate is None:
        failures.append("live eval task_success_rate is malformed")
    elif require_threshold and success_rate < LIVE_EVAL_MIN_TASK_SUCCESS_RATE:
        failures.append("live eval task_success_rate below threshold")
    pricing = payload.get("pricing")
    if not isinstance(pricing, Mapping) or pricing.get("cost_status") != "unknown":
        failures.append("live eval evidence must report unknown pricing")
    result_failures, recomputed_rate = _validate_results(payload.get("results"))
    failures.extend(result_failures)
    if (
        success_rate is not None
        and recomputed_rate is not None
        and abs(success_rate - recomputed_rate) > 0.000001
    ):
        failures.append("live eval task_success_rate does not match per-case results")
    return failures


def read_limited_live_eval_public_bytes(path: Path) -> bytes:
    """Read a live public artifact only after enforcing the D11 size cap."""

    if path.stat().st_size > MAX_LIVE_EVIDENCE_JSON_BYTES:
        raise ValueError("live eval public evidence exceeds 64000 bytes")
    data = path.read_bytes()
    if len(data) > MAX_LIVE_EVIDENCE_JSON_BYTES:
        raise ValueError("live eval public evidence exceeds 64000 bytes")
    return data


def load_live_eval_public_payload(path: Path) -> Any:
    data = read_limited_live_eval_public_bytes(path)
    return json.loads(data.decode("utf-8"))


def _validate_registered_cases(value: object) -> list[str]:
    if not isinstance(value, list):
        return ["live eval case registry is missing"]
    registry_by_id = {case.id: case for case in LIVE_EVAL_CASE_REGISTRY}
    ids = [item.get("id") for item in value if isinstance(item, Mapping)]
    if ids != [case.id for case in LIVE_EVAL_CASE_REGISTRY]:
        return ["live eval case registry does not match registered ids"]
    failures: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            failures.append("live eval case registry entries must be objects")
            continue
        case = registry_by_id[str(item["id"])]
        if item.get("question") != case.question:
            failures.append(f"live eval case question mismatch: {case.id}")
        for field_name in (
            "expected_tools",
            "allowed_tools",
            "forbidden_tools",
            "allowed_sources",
            "security_assertions",
        ):
            if tuple(item.get(field_name) or ()) != getattr(case, field_name):
                failures.append(f"live eval case contract mismatch: {case.id}")
                break
        if item.get("expected_answer_status") != case.expected_answer_status:
            failures.append(f"live eval case answer status mismatch: {case.id}")
        if item.get("citation_required") is not case.citation_required:
            failures.append(f"live eval case citation contract mismatch: {case.id}")
        if item.get("success_rule") != case.success_rule:
            failures.append(f"live eval case success rule mismatch: {case.id}")
    return failures


def _validate_results(value: object) -> tuple[list[str], float | None]:
    if not isinstance(value, list):
        return ["live eval evidence results are missing"], None
    registry_by_id = {case.id: case for case in LIVE_EVAL_CASE_REGISTRY}
    expected_ids = [case.id for case in LIVE_EVAL_CASE_REGISTRY]
    result_ids = [item.get("case_id") for item in value if isinstance(item, Mapping)]
    failures: list[str] = []
    if result_ids != expected_ids:
        failures.append("live eval results do not match registered case ids")
    success_count = 0
    for item in value:
        if not isinstance(item, Mapping):
            failures.append("live eval result entries must be objects")
            continue
        case_id = item.get("case_id")
        case = registry_by_id.get(case_id) if isinstance(case_id, str) else None
        if case is None:
            continue
        case_failures = _validate_result_for_case(item, case)
        failures.extend(case_failures)
        if item.get("task_success") is True:
            success_count += 1
    if len(value) != len(LIVE_EVAL_CASE_REGISTRY):
        failures.append("live eval evidence results do not match case_count")
        return failures, None
    return failures, _rate(success_count, len(LIVE_EVAL_CASE_REGISTRY))


def _validate_result_for_case(
    result: Mapping[str, Any], case: LiveEvalCaseContract
) -> list[str]:
    failures: list[str] = []
    required = (
        "task_success",
        "answer_status",
        "answer_fallback",
        "stop_reason",
        "state",
        "tool_calls",
        "sources",
        "phase_statuses",
        "model_roles",
        "tokens",
        "duration_ms",
        "cost_status",
        "grounding",
        "security",
    )
    for field_name in required:
        if field_name not in result:
            failures.append(f"live eval result is incomplete: {case.id}")
            return failures
    if not isinstance(result.get("task_success"), bool):
        failures.append(f"live eval result task_success must be boolean: {case.id}")
    tool_calls = _string_list(result.get("tool_calls"))
    if tool_calls is None:
        failures.append(f"live eval result tool_calls are malformed: {case.id}")
        tool_calls = ()
    sources = result.get("sources")
    if not isinstance(sources, list) or not all(
        isinstance(source, Mapping) for source in sources
    ):
        failures.append(f"live eval result sources are malformed: {case.id}")
        sources = []
    if not isinstance(result.get("phase_statuses"), list):
        failures.append(f"live eval result phase_statuses are malformed: {case.id}")
    if not isinstance(result.get("model_roles"), list):
        failures.append(f"live eval result model_roles are malformed: {case.id}")
    if not isinstance(result.get("tokens"), Mapping):
        failures.append(f"live eval result tokens are malformed: {case.id}")
    if not isinstance(result.get("grounding"), Mapping):
        failures.append(f"live eval result grounding is malformed: {case.id}")
    security = result.get("security")
    if not isinstance(security, Mapping):
        failures.append(f"live eval result security is malformed: {case.id}")
        security = {}
    if _integer_value(security.get("security_failures")) != 0:
        failures.append(f"live eval result has security failures: {case.id}")
    if _integer_value(security.get("hidden_writes")) != 0:
        failures.append(f"live eval result has hidden writes: {case.id}")
    forbidden_executions = security.get("forbidden_tool_executions")
    if not isinstance(forbidden_executions, list) or forbidden_executions:
        failures.append(f"live eval result has forbidden tool executions: {case.id}")
    unexpected_tools = sorted(set(tool_calls) - set(case.allowed_tools))
    if unexpected_tools:
        failures.append(f"live eval result has unregistered tool calls: {case.id}")
    if any(tool in tool_calls for tool in case.forbidden_tools):
        failures.append(f"live eval result has forbidden tool calls: {case.id}")
    if result.get("answer_status") == "grounded" and not _has_cited_allowed_source(
        sources, case.allowed_sources
    ):
        failures.append(f"live eval result lacks required citation: {case.id}")
    if result.get("task_success") is True:
        if result.get("answer_status") != case.expected_answer_status:
            failures.append(f"live eval successful result has wrong status: {case.id}")
        if result.get("answer_fallback") is not False:
            failures.append(f"live eval successful result used fallback: {case.id}")
        for tool_name in case.expected_tools:
            if tool_name not in tool_calls:
                failures.append(
                    f"live eval successful result lacks expected tool: {case.id}"
                )
        if case.citation_required and not _has_cited_allowed_source(
            sources, case.allowed_sources
        ):
            failures.append(
                f"live eval successful result lacks allowed source citation: {case.id}"
            )
    return failures


def _has_cited_allowed_source(
    sources: Sequence[object], allowed_sources: Sequence[str]
) -> bool:
    allowed = set(allowed_sources)
    for raw_source in sources:
        if not isinstance(raw_source, Mapping):
            continue
        has_allowed_label = any(
            isinstance(raw_source.get(key), str) and raw_source[key] in allowed
            for key in ("file_name", "title", "url")
        )
        cite_index = raw_source.get("cite_index")
        if has_allowed_label and isinstance(cite_index, int) and not isinstance(
            cite_index, bool
        ):
            return True
    return False


def _string_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    result = tuple(item for item in value if isinstance(item, str))
    if len(result) != len(value):
        return None
    return result


def _integer_value(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _bounded_rate_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    rate = float(value)
    if 0.0 <= rate <= 1.0:
        return rate
    return None


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)
