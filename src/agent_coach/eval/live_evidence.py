"""Validation helpers for redacted D11 live-provider public evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_coach.core.contracts import CONTRACT_SCHEMA_HASH
from agent_coach.retrieval.corpus import load_diploma_knowledge_base

LIVE_EVAL_PUBLIC_SCHEMA_VERSION = "agent-coach-live-eval-public/1.0.0"
LIVE_EVAL_PUBLIC_PROVENANCE = {
    "classification": "redacted_live_provider_eval_public",
    "contains_credentials": False,
    "contains_learner_data": False,
    "contains_hometutor_runtime_dependency": False,
    "contains_raw_provider_payloads": False,
}
HISTORICAL_LIVE_EVAL_CLASSIFICATION = "historical_example"
HISTORICAL_LIVE_EVAL_PUBLIC_PROVENANCE = {
    **LIVE_EVAL_PUBLIC_PROVENANCE,
    "classification": HISTORICAL_LIVE_EVAL_CLASSIFICATION,
}
LIVE_EVAL_MIN_TASK_SUCCESS_RATE = 0.8
MAX_LIVE_EVIDENCE_JSON_BYTES = 64_000
MAX_PROVENANCE_FAILURE_CHARS = 240
MAX_DYNAMIC_PUBLIC_TEXT_CHARS = 240
LIVE_EXECUTION_BACKEND = "live_provider"
SCRIPTED_EXECUTION_BACKEND = "scripted_responses_client"
SCRIPTED_MODEL_IDS = frozenset({"scripted-planner", "scripted-synthesizer"})
HISTORICAL_EVIDENCE_PREFIX = "docs/evidence/historical/"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PUBLIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
SECRETISH_PUBLIC_VALUE_PATTERN = re.compile(
    r"(api[_-]?key|bearer|password|secret|token|sk-[A-Za-z0-9])",
    re.IGNORECASE,
)
PRIVATE_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    re.compile(r"(?<![:/])/(?:home|Users|opt|var|tmp|mnt|etc|private|root)/"),
)
RAW_PROVIDER_TEXT_MARKERS = (
    "raw_provider_payload",
    "response_id",
)
RAW_PROVIDER_ID_PATTERN = re.compile(r"\bresp_[A-Za-z0-9]", re.IGNORECASE)
DYNAMIC_PUBLIC_TEXT_KEYS = frozenset({"error", "detail", "note"})
IDENTIFIER_PUBLIC_KEYS = frozenset({"role", "model_id", "backend"})
UNEXPECTED_PUBLIC_FIELD_FAILURE = "public live evidence has unexpected fields"
UNSAFE_PUBLIC_VALUE_FAILURE = "current live evidence has unsafe public values"
CURRENT_LIVE_EVAL_KEYS = frozenset(
    {
        "schema_version",
        "provenance",
        "repository",
        "profile",
        "mode",
        "contains_scripted_responses",
        "provider_profile_opt_in",
        "execution_backend",
        "evaluated_commit",
        "clean_worktree",
        "contract_hash",
        "corpus_hash",
        "case_registry_hash",
        "model_projection",
        "checked_at_utc",
        "case_count",
        "task_success_rate",
        "fallback_count",
        "abstain_count",
        "model_roles",
        "limits",
        "pricing",
        "cases",
        "results",
    }
)
PROVENANCE_KEYS = frozenset(
    {
        "classification",
        "contains_credentials",
        "contains_learner_data",
        "contains_hometutor_runtime_dependency",
        "contains_raw_provider_payloads",
    }
)
MODEL_PROJECTION_KEYS = frozenset({"planner", "synthesizer"})
MODEL_ROLE_KEYS = frozenset({"role", "model_id", "backend"})
LIMIT_KEYS = frozenset(
    {
        "timeout_sec",
        "max_retries",
        "max_output_tokens",
        "max_question_chars",
        "max_run_tokens",
        "run_time_limit_sec",
        "cost_cap_usd",
        "routing_status",
    }
)
PRICING_KEYS = frozenset({"cost_status", "monetary_cap_usd", "note"})
RESULT_KEYS = frozenset(
    {
        "case_id",
        "task_success",
        "error",
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
        "total_cost_usd",
        "grounding",
        "security",
    }
)
SOURCE_KEYS = frozenset({"file_name", "title", "url", "cite_index"})
PHASE_KEYS = frozenset({"name", "status", "detail"})
TOKEN_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens"})
GROUNDING_KEYS = frozenset(
    {
        "answer_status",
        "has_retrieval_evidence",
        "has_source_citation",
        "source_count",
    }
)
SECURITY_KEYS = frozenset(
    {
        "security_failures",
        "hidden_writes",
        "forbidden_tool_executions",
    }
)
PUBLIC_CASE_FIELDS = (
    "id",
    "question",
    "expected_tools",
    "allowed_tools",
    "forbidden_tools",
    "expected_answer_status",
    "allowed_sources",
    "citation_required",
    "security_assertions",
    "success_rule",
)


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


LiveEvalCaseContract = LiveEvalCase

LIVE_EVAL_CASE_REGISTRY: tuple[LiveEvalCase, ...] = (
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
LIVE_EVAL_CASES = LIVE_EVAL_CASE_REGISTRY


def public_case_contract(case: LiveEvalCase) -> dict[str, Any]:
    """Return the public registry projection for one live eval case."""

    payload: dict[str, Any] = {}
    for field_name in PUBLIC_CASE_FIELDS:
        value = getattr(case, field_name)
        payload[field_name] = list(value) if isinstance(value, tuple) else value
    return payload


def executable_case_contract(case: LiveEvalCase) -> dict[str, Any]:
    """Return the registry projection used by the live search call and runner."""

    payload = public_case_contract(case)
    payload["search_query"] = case.search_query
    payload["scripted_answer"] = case.scripted_answer
    return payload


def live_eval_contract_hash() -> str:
    return CONTRACT_SCHEMA_HASH


@lru_cache(maxsize=1)
def live_eval_corpus_hash() -> str:
    return load_diploma_knowledge_base().corpus_hash


def live_eval_case_registry_hash() -> str:
    return hashlib.sha256(
        json.dumps(
            [executable_case_contract(case) for case in LIVE_EVAL_CASE_REGISTRY],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def is_historical_live_eval_path(path: Path | str) -> bool:
    label = str(path).replace("\\", "/").lstrip("./")
    return label.startswith(HISTORICAL_EVIDENCE_PREFIX)


def is_historical_live_eval_payload(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    return provenance.get("classification") == HISTORICAL_LIVE_EVAL_CLASSIFICATION


def bounded_live_eval_failure(failures: Sequence[str]) -> str:
    """Return one public-safe provenance failure without provider payload."""

    if not failures:
        return "live eval public evidence is invalid"
    text = " ".join(str(failures[0]).split())
    if len(text) > MAX_PROVENANCE_FAILURE_CHARS:
        return text[: MAX_PROVENANCE_FAILURE_CHARS - 3] + "..."
    return text


def validate_live_eval_public_payload(
    payload: object, *, require_threshold: bool = True
) -> list[str]:
    """Return validation failures for the 1.0.0 redacted live public schema."""

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


def validate_current_live_eval_public_payload(
    payload: object,
    *,
    require_threshold: bool = True,
    expected_commit: str | None = None,
    path: Path | str | None = None,
) -> list[str]:
    """Return failures for a current causal live public artifact."""

    if path is not None and is_historical_live_eval_path(path):
        return ["historical example is not current live evidence"]
    if is_historical_live_eval_payload(payload):
        return ["historical example is not current live evidence"]
    if not isinstance(payload, Mapping):
        return ["live eval public evidence must be a JSON object"]
    if _current_payload_has_unexpected_fields(payload):
        return [UNEXPECTED_PUBLIC_FIELD_FAILURE]
    if _current_payload_has_unsafe_values(payload):
        return [UNSAFE_PUBLIC_VALUE_FAILURE]
    failures = validate_live_eval_public_payload(
        payload, require_threshold=require_threshold
    )
    evaluated_commit = payload.get("evaluated_commit")
    if not isinstance(evaluated_commit, str) or not COMMIT_RE.fullmatch(
        evaluated_commit
    ):
        failures.append("current live evidence requires evaluated_commit")
    elif expected_commit is not None and evaluated_commit != expected_commit:
        failures.append("live eval evaluated_commit does not match expected commit")
    if payload.get("clean_worktree") is not True:
        failures.append("current live evidence requires a clean worktree")
    if payload.get("contract_hash") != live_eval_contract_hash():
        failures.append("live eval contract_hash does not match the public contract")
    if payload.get("corpus_hash") != live_eval_corpus_hash():
        failures.append("live eval corpus_hash does not match the packaged corpus")
    if payload.get("case_registry_hash") != live_eval_case_registry_hash():
        failures.append("live eval case_registry_hash does not match the registry")
    if payload.get("execution_backend") != LIVE_EXECUTION_BACKEND:
        failures.append("scripted runner output is not current live evidence")
    failures.extend(_validate_model_projection(payload.get("model_projection")))
    return failures


def validate_historical_live_eval_public_payload(payload: object) -> list[str]:
    """Return public-safety failures for a historical live example."""

    if not isinstance(payload, Mapping):
        return ["historical live example must be a JSON object"]
    failures: list[str] = []
    if payload.get("schema_version") != LIVE_EVAL_PUBLIC_SCHEMA_VERSION:
        failures.append("historical live example schema is invalid")
    provenance = payload.get("provenance")
    if provenance != HISTORICAL_LIVE_EVAL_PUBLIC_PROVENANCE:
        failures.append("historical live example provenance is invalid")
    if payload.get("contains_scripted_responses") is True:
        failures.append("historical live example must not contain scripted responses")
    if not isinstance(payload.get("cases"), list) or not payload.get("cases"):
        failures.append("historical live example cases are missing")
    if not isinstance(payload.get("results"), list) or not payload.get("results"):
        failures.append("historical live example results are missing")
    historical_commit = payload.get("historical_evaluated_commit")
    if historical_commit is not None and (
        not isinstance(historical_commit, str)
        or not COMMIT_RE.fullmatch(historical_commit)
    ):
        failures.append("historical_evaluated_commit is malformed")
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


def _current_payload_has_unexpected_fields(payload: Mapping[str, Any]) -> bool:
    if _has_unexpected_keys(payload, CURRENT_LIVE_EVAL_KEYS):
        return True
    provenance = payload.get("provenance")
    if isinstance(provenance, Mapping) and _has_unexpected_keys(
        provenance, PROVENANCE_KEYS
    ):
        return True
    projection = payload.get("model_projection")
    if isinstance(projection, Mapping):
        if _has_unexpected_keys(projection, MODEL_PROJECTION_KEYS):
            return True
        for role_projection in projection.values():
            if isinstance(role_projection, Mapping) and _has_unexpected_keys(
                role_projection, MODEL_ROLE_KEYS
            ):
                return True
    limits = payload.get("limits")
    if isinstance(limits, Mapping) and _has_unexpected_keys(limits, LIMIT_KEYS):
        return True
    pricing = payload.get("pricing")
    if isinstance(pricing, Mapping) and _has_unexpected_keys(pricing, PRICING_KEYS):
        return True
    cases = payload.get("cases")
    if isinstance(cases, list):
        allowed_case_keys = frozenset(PUBLIC_CASE_FIELDS)
        for case in cases:
            if isinstance(case, Mapping) and _has_unexpected_keys(
                case, allowed_case_keys
            ):
                return True
    results = payload.get("results")
    if isinstance(results, list):
        for result in results:
            if isinstance(result, Mapping) and _result_has_unexpected_fields(result):
                return True
    return False


def _result_has_unexpected_fields(result: Mapping[str, Any]) -> bool:
    if _has_unexpected_keys(result, RESULT_KEYS):
        return True
    sources = result.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, Mapping) and _has_unexpected_keys(
                source, SOURCE_KEYS
            ):
                return True
    phases = result.get("phase_statuses")
    if isinstance(phases, list):
        for phase in phases:
            if isinstance(phase, Mapping) and _has_unexpected_keys(phase, PHASE_KEYS):
                return True
    tokens = result.get("tokens")
    if isinstance(tokens, Mapping) and _has_unexpected_keys(tokens, TOKEN_KEYS):
        return True
    grounding = result.get("grounding")
    if isinstance(grounding, Mapping) and _has_unexpected_keys(
        grounding, GROUNDING_KEYS
    ):
        return True
    security = result.get("security")
    return isinstance(security, Mapping) and _has_unexpected_keys(
        security, SECURITY_KEYS
    )


def _has_unexpected_keys(value: Mapping[str, Any], allowed: frozenset[str]) -> bool:
    return any(key not in allowed for key in value)


def _current_payload_has_unsafe_values(
    value: object, *, identifier: bool = False, field: str | None = None
) -> bool:
    if isinstance(value, str):
        return _public_text_is_unsafe(value, identifier=identifier, field=field)
    if isinstance(value, Mapping):
        return any(
            _current_payload_has_unsafe_values(
                item,
                identifier=key in IDENTIFIER_PUBLIC_KEYS,
                field=key if isinstance(key, str) else None,
            )
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(
            _current_payload_has_unsafe_values(item, field=field) for item in value
        )
    return False


def _public_text_is_unsafe(
    value: str, *, identifier: bool, field: str | None = None
) -> bool:
    stripped = value.strip()
    if identifier and (not stripped or not PUBLIC_ID_PATTERN.fullmatch(stripped)):
        return True
    if (
        field in DYNAMIC_PUBLIC_TEXT_KEYS
        and len(value) > MAX_DYNAMIC_PUBLIC_TEXT_CHARS
    ):
        return True
    if SECRETISH_PUBLIC_VALUE_PATTERN.search(value):
        return True
    if any(pattern.search(value) for pattern in PRIVATE_PATH_PATTERNS):
        return True
    folded = value.casefold()
    if "chain-of-thought" in folded or "begin private key" in folded:
        return True
    if any(marker in folded for marker in RAW_PROVIDER_TEXT_MARKERS):
        return True
    return RAW_PROVIDER_ID_PATTERN.search(value) is not None


def _validate_model_projection(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return ["current live evidence requires a safe model projection"]
    failures: list[str] = []
    for role in ("planner", "synthesizer"):
        projection = value.get(role)
        if not isinstance(projection, Mapping):
            failures.append("current live evidence requires a safe model projection")
            continue
        model_id = projection.get("model_id")
        backend = projection.get("backend")
        role_value = projection.get("role")
        if any(
            not isinstance(item, str) or _public_text_is_unsafe(item, identifier=True)
            for item in (model_id, backend, role_value)
        ):
            failures.append(UNSAFE_PUBLIC_VALUE_FAILURE)
            continue
        if model_id in SCRIPTED_MODEL_IDS or model_id.startswith("scripted-"):
            failures.append("scripted runner output is not current live evidence")
        if role_value != role:
            failures.append("current live evidence model role is invalid")
    return failures


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
        expected = public_case_contract(case)
        if item.get("question") != expected["question"]:
            failures.append(f"live eval case question mismatch: {case.id}")
        for field_name in (
            "expected_tools",
            "allowed_tools",
            "forbidden_tools",
            "allowed_sources",
            "security_assertions",
        ):
            if tuple(item.get(field_name) or ()) != tuple(expected[field_name]):
                failures.append(f"live eval case contract mismatch: {case.id}")
                break
        if item.get("expected_answer_status") != expected["expected_answer_status"]:
            failures.append(f"live eval case answer status mismatch: {case.id}")
        if item.get("citation_required") is not expected["citation_required"]:
            failures.append(f"live eval case citation contract mismatch: {case.id}")
        if item.get("success_rule") != expected["success_rule"]:
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
    result: Mapping[str, Any], case: LiveEvalCase
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
