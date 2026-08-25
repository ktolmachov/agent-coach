"""Run the bounded offline acceptance demonstration for Agent Coach."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_coach import __version__
from agent_coach.core.security import trace_text
from agent_coach.retrieval import build_local_vector_composition

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA_VERSION = "agent-coach-acceptance-demo/1.3.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8008
API_START_TIMEOUT_SEC = 15.0
MAX_FAILURE_SUMMARY_CHARS = 1200
FORBIDDEN_TOOL_ARG_KEYS = frozenset(
    {"run_id", "user_id", "session_id", "query_options"}
)
EXPECTED_DEMO_TOOL_CHAIN = (
    "learner.get_profile",
    "rag.search",
    "quiz.generate",
)


@dataclass(frozen=True)
class CommandSpec:
    key: str
    label: str
    args: tuple[str, ...]
    timeout_sec: float = 120.0


@dataclass(frozen=True)
class StepResult:
    key: str
    label: str
    status: str
    duration_ms: float
    summary: str
    command: tuple[str, ...] = ()
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True)
class ContrastCaseSpec:
    scenario_id: str
    question: str
    expected_tools: tuple[str, ...]
    expected_answer_status: str
    expected_source_count: int
    expected_retrieval_evidence: bool
    expected_citation: bool


@dataclass(frozen=True)
class CompletedDemoCase:
    spec: ContrastCaseSpec
    accepted: dict[str, Any]
    completed: dict[str, Any]


@dataclass(frozen=True)
class HttpJsonObservation:
    status_code: int
    body: dict[str, Any]


CONTRAST_CASES = (
    ContrastCaseSpec(
        scenario_id="grounded_success",
        question="Explain photosynthesis and suggest practice.",
        expected_tools=EXPECTED_DEMO_TOOL_CHAIN,
        expected_answer_status="grounded",
        expected_source_count=1,
        expected_retrieval_evidence=True,
        expected_citation=True,
    ),
    ContrastCaseSpec(
        scenario_id="empty_cards",
        question="What cards are due now?",
        expected_tools=("cards.get_due",),
        expected_answer_status="abstain",
        expected_source_count=0,
        expected_retrieval_evidence=False,
        expected_citation=False,
    ),
    ContrastCaseSpec(
        scenario_id="prompt_injection",
        question="Search content containing injection text.",
        expected_tools=("rag.search",),
        expected_answer_status="abstain",
        expected_source_count=1,
        expected_retrieval_evidence=False,
        expected_citation=False,
    ),
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic offline commissioning and acceptance demo."
        ),
    )
    parser.add_argument(
        "--full-checks",
        action="store_true",
        help="Also run the full test suite, Ruff and compileall.",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="Fail preflight when the Git worktree is dirty.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Keep the localhost API and Swagger UI running until Ctrl+C.",
    )
    parser.add_argument(
        "--port",
        type=_port_number,
        default=DEFAULT_PORT,
        help=f"Loopback API port; default {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path outside the repository checkout.",
    )
    return parser


def command_plan(*, full_checks: bool) -> tuple[CommandSpec, ...]:
    python = sys.executable
    checks: list[CommandSpec] = [
        CommandSpec(
            "package_artifact",
            "Wheel artifact smoke",
            (python, "-m", "pytest", "tests/test_package_smoke.py", "-q"),
        ),
        CommandSpec(
            "contract_export",
            "Exported contract integrity",
            (python, "scripts/check_contract_export.py"),
        ),
        CommandSpec(
            "openapi_snapshot",
            "OpenAPI snapshot",
            (python, "scripts/check_openapi_snapshot.py"),
        ),
        CommandSpec(
            "drift_gate",
            "Architecture drift gate",
            (python, "scripts/check_drift_gate.py"),
        ),
        CommandSpec(
            "public_release",
            "Public release safety gate",
            (python, "scripts/check_public_release.py"),
        ),
    ]
    if full_checks:
        checks.extend(
            (
                CommandSpec(
                    "full_tests",
                    "Full public test suite",
                    (python, "-m", "pytest", "-q"),
                    timeout_sec=300.0,
                ),
                CommandSpec(
                    "ruff",
                    "Ruff static checks",
                    (python, "-m", "ruff", "check", "."),
                ),
                CommandSpec(
                    "compileall",
                    "Python bytecode compilation",
                    (python, "-m", "compileall", "-q", "src", "scripts"),
                ),
            )
        )
    checks.extend(
        (
            CommandSpec(
                "offline_eval",
                "D11 offline eval gate",
                (python, "scripts/run_eval_gate.py"),
            ),
            CommandSpec(
                "mock_profile",
                "Deterministic mock profile",
                (python, "scripts/run_diploma_demo.py"),
            ),
            CommandSpec(
                "scripted_provider",
                "Scripted provider contract",
                (python, "scripts/run_live_eval.py", "--scripted"),
            ),
        )
    )
    return tuple(checks)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
    args = build_arg_parser().parse_args(argv)
    if args.output is not None and _is_repo_local(args.output):
        print("Acceptance reports must be written outside the checkout.")
        return 2

    print("=== Agent Coach acceptance demonstration ===")
    metadata, preflight = _run_preflight(require_clean=args.require_clean)
    steps: list[StepResult] = [preflight]
    _print_step(preflight)
    server: subprocess.Popen[str] | None = None

    if preflight.status == "PASS":
        for spec in command_plan(full_checks=args.full_checks):
            step = _run_command(spec)
            steps.append(step)
            _print_step(step)
            if step.status != "PASS":
                break

    if all(step.status == "PASS" for step in steps):
        local_vector = _run_local_vector_demo()
        steps.append(local_vector)
        _print_step(local_vector)

    if all(step.status == "PASS" for step in steps):
        api_steps, server = _start_and_smoke_api(args.port)
        steps.extend(api_steps)
        for step in api_steps:
            _print_step(step)

    passed = all(step.status == "PASS" for step in steps)
    report = _build_report(
        metadata=metadata,
        steps=steps,
        full_checks=args.full_checks,
        port=args.port,
        overall_status="PASS" if passed else "FAIL",
    )
    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"Cannot write acceptance report: {_bounded_failure(exc)}")
            if server is not None:
                _stop_process(server)
            return 2
        print(f"Report: {args.output}")

    print(f"OVERALL: {report['overall_status']}")
    if server is not None and passed and args.serve:
        print(f"Swagger UI: http://{DEFAULT_HOST}:{args.port}/docs")
        print("Press Ctrl+C to stop the local demo API.")
        try:
            server.wait()
        except KeyboardInterrupt:
            print("Stopping the local demo API...")
        finally:
            _stop_process(server)
        return 0

    if server is not None:
        _stop_process(server)
    return 0 if passed else 1


def _run_preflight(*, require_clean: bool) -> tuple[dict[str, Any], StepResult]:
    started = time.perf_counter()
    commit = _git_output("rev-parse", "HEAD", fallback="unknown")
    status = _git_output("status", "--short", fallback="unavailable")
    status_available = status != "unavailable"
    dirty = bool(status) if status_available else True
    failures: list[str] = []
    if commit == "unknown":
        failures.append("Git HEAD is unavailable")
    if not status_available:
        failures.append("Git status is unavailable")
    if require_clean and dirty:
        failures.append("clean worktree required")
    summary = (
        "; ".join(failures)
        if failures
        else f"agent-coach {__version__}; commit={commit[:12]}; dirty={dirty}"
    )
    metadata = {
        "agent_coach_version": __version__,
        "python_version": ".".join(str(item) for item in sys.version_info[:3]),
        "commit": commit,
        "worktree_dirty": dirty,
    }
    return metadata, StepResult(
        key="preflight",
        label="Environment preflight",
        status="FAIL" if failures else "PASS",
        duration_ms=_elapsed_ms(started),
        summary=summary,
    )


def _run_command(spec: CommandSpec) -> StepResult:
    started = time.perf_counter()
    try:
        process = subprocess.run(
            spec.args,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=spec.timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            key=spec.key,
            label=spec.label,
            status="FAIL",
            duration_ms=_elapsed_ms(started),
            summary=f"timed out after {spec.timeout_sec:g} seconds",
            command=_public_command(spec.args),
        )
    combined = "\n".join(part for part in (process.stdout, process.stderr) if part)
    status = "PASS" if process.returncode == 0 else "FAIL"
    summary = (
        _successful_command_summary(spec.key, process.stdout)
        if process.returncode == 0
        else _bounded_failure(combined)
    )
    return StepResult(
        key=spec.key,
        label=spec.label,
        status=status,
        duration_ms=_elapsed_ms(started),
        summary=summary,
        command=_public_command(spec.args),
    )


def _run_local_vector_demo() -> StepResult:
    started = time.perf_counter()
    try:
        composition = build_local_vector_composition(
            "How does photosynthesis store light energy in glucose?",
            run_id="acceptance-local-vector",
        )
        result = composition.runner.run(composition.request)
        if result.answer_status != "grounded" or not result.sources:
            raise RuntimeError("local-vector result was not grounded")
        source = str(result.sources[0].get("file_name") or "unknown")
    except Exception as exc:  # noqa: BLE001 - top-level demo boundary
        return StepResult(
            key="local_vector",
            label="Local-vector profile",
            status="FAIL",
            duration_ms=_elapsed_ms(started),
            summary=_bounded_failure(str(exc)),
        )
    return StepResult(
        key="local_vector",
        label="Local-vector profile",
        status="PASS",
        duration_ms=_elapsed_ms(started),
        summary=f"grounded=True; source={source}; cost=local_zero",
    )


def _start_and_smoke_api(
    port: int,
) -> tuple[tuple[StepResult, ...], subprocess.Popen[str] | None]:
    started = time.perf_counter()
    if not _port_is_available(port):
        return (
            (
                StepResult(
                    key="mock_api",
                    label="Localhost Mock API",
                    status="FAIL",
                    duration_ms=_elapsed_ms(started),
                    summary=f"loopback port {port} is already in use",
                ),
            ),
            None,
        )
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_coach.api", "--port", str(port)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        health = _wait_for_json(process, port, "/healthz")
        ready = _http_json(port, "/readyz")
        contracts = _http_json(port, "/v1/demo/contracts")
        tools = _http_json(port, "/v1/demo/tools")
        completed_cases = [_submit_demo_run(port, spec) for spec in CONTRAST_CASES]
        grounded_case = completed_cases[0]
        tool_items = tools.get("tools")
        if health.get("ok") is not True or ready.get("ok") is not True:
            raise RuntimeError("health/readiness check failed")
        if health.get("production_auth") is not False:
            raise RuntimeError("unexpected production authentication claim")
        if not isinstance(tool_items, list) or not tool_items:
            raise RuntimeError("API advertised no demo tools")
        if not contracts.get("contract_schema_hash"):
            raise RuntimeError("API contract projection is incomplete")
        api_step = StepResult(
            key="mock_api",
            label="Localhost Mock API",
            status="PASS",
            duration_ms=_elapsed_ms(started),
            summary=(
                f"health=ok; tools={len(tool_items)}; runs={len(completed_cases)}; "
                f"swagger=http://{DEFAULT_HOST}:{port}/docs"
            ),
        )
        chain_step = _verify_agentic_chain(
            question=grounded_case.spec.question,
            completed=grounded_case.completed,
            advertised_tools=tool_items,
        )
        contrast_step = _verify_contrastive_routing(
            completed_cases=completed_cases,
            advertised_tools=tool_items,
        )
        reproducibility_step = _verify_reproducibility_and_tool_args(
            port=port,
            completed_cases=completed_cases,
            advertised_tools=tool_items,
        )
        fail_closed_step = _verify_fail_closed_http(port)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        details = _process_failure_details(process, exc)
        _stop_process(process)
        return (
            (
                StepResult(
                    key="mock_api",
                    label="Localhost Mock API",
                    status="FAIL",
                    duration_ms=_elapsed_ms(started),
                    summary=details,
                ),
            ),
            None,
        )
    verification_steps = (
        chain_step,
        contrast_step,
        reproducibility_step,
        fail_closed_step,
    )
    if any(step.status != "PASS" for step in verification_steps):
        _stop_process(process)
        return (api_step, *verification_steps), None
    return (
        (api_step, *verification_steps),
        process,
    )


def _submit_demo_run(port: int, spec: ContrastCaseSpec) -> CompletedDemoCase:
    accepted = _http_json(
        port,
        "/v1/runs",
        method="POST",
        payload={"scenario_id": spec.scenario_id, "question": spec.question},
        headers={
            "Idempotency-Key": f"acceptance-commission-{spec.scenario_id}"
        },
    )
    polling_url = str(accepted.get("polling_url") or "")
    if not polling_url.startswith("/v1/runs/"):
        raise RuntimeError(f"{spec.scenario_id}: invalid polling URL")
    return CompletedDemoCase(
        spec=spec,
        accepted=accepted,
        completed=_http_json(port, polling_url),
    )


def _verify_agentic_chain(
    *,
    question: str,
    completed: dict[str, Any],
    advertised_tools: list[object],
) -> StepResult:
    """Prove that the HTTP result contains a complete grounded agent chain."""
    started = time.perf_counter()
    result = completed.get("result")
    failures: list[str] = []
    if completed.get("state") != "completed":
        failures.append("run state is not completed")
    if not isinstance(result, dict):
        failures.append("run result is missing")
        result = {}

    answer = result.get("answer")
    answer_text = answer if isinstance(answer, str) else ""
    raw_steps = result.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    tool_steps = [
        item
        for item in steps
        if isinstance(item, dict) and isinstance(item.get("tool_name"), str)
    ]
    selected_tools = [str(item["tool_name"]) for item in tool_steps]
    if tuple(selected_tools) != EXPECTED_DEMO_TOOL_CHAIN:
        failures.append("selected tool chain does not match the demo contract")
    if any(item.get("tool_ok") is not True for item in tool_steps):
        failures.append("one or more selected tools did not succeed")

    advertised_names = {
        str(item["name"])
        for item in advertised_tools
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if not set(selected_tools).issubset(advertised_names):
        failures.append("result used a tool not advertised by the API")

    trace = result.get("trace")
    trace = trace if isinstance(trace, dict) else {}
    trace_tools = trace.get("tool_calls")
    if trace_tools != selected_tools:
        failures.append("step tool selection and trace tool calls disagree")
    raw_phases = trace.get("phases")
    phases = raw_phases if isinstance(raw_phases, list) else []
    retrieval_phase = next(
        (
            phase
            for phase in phases
            if isinstance(phase, dict) and phase.get("name") == "knowledge_retrieval"
        ),
        None,
    )
    retrieval = (
        retrieval_phase.get("retrieval")
        if isinstance(retrieval_phase, dict)
        else None
    )
    if (
        not isinstance(retrieval_phase, dict)
        or retrieval_phase.get("status") != "completed"
        or not isinstance(retrieval, dict)
        or retrieval.get("has_grounding_evidence") is not True
    ):
        failures.append("retrieval phase has no completed grounding evidence")

    raw_sources = result.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    source_labels = [label for source in sources if (label := _source_label(source))]
    if not sources or len(source_labels) != len(sources):
        failures.append("retrieved context has no public source labels")

    grounding = trace.get("grounding")
    grounding = grounding if isinstance(grounding, dict) else {}
    if grounding.get("has_retrieval_evidence") is not True:
        failures.append("grounding summary has no retrieval evidence")
    if grounding.get("has_source_citation") is not True:
        failures.append("grounding summary has no source citation")
    if grounding.get("source_count") != len(sources):
        failures.append("grounding source count disagrees with result sources")

    citation_markers = [
        f"[{source['cite_index']}]"
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("cite_index"), int)
    ]
    if not citation_markers or not any(
        marker in answer_text for marker in citation_markers
    ):
        failures.append("final answer does not cite the retrieved context")
    if result.get("success") is not True or result.get("answer_status") != "grounded":
        failures.append("final answer is not a successful grounded result")
    if not answer_text.strip():
        failures.append("final answer is empty")

    evidence = {
        "question": trace_text(question, max_chars=500),
        "selected_tools": selected_tools,
        "context": {
            "source_count": len(sources),
            "source_labels": source_labels,
            "retrieval_evidence": grounding.get("has_retrieval_evidence") is True,
        },
        "answer": trace_text(answer_text, max_chars=800),
        "answer_status": result.get("answer_status"),
        "citation_present": grounding.get("has_source_citation") is True,
    }
    return StepResult(
        key="agentic_chain",
        label="Agentic execution chain",
        status="FAIL" if failures else "PASS",
        duration_ms=_elapsed_ms(started),
        summary=(
            _bounded_failure("; ".join(failures))
            if failures
            else (
                f"question -> {len(selected_tools)} tools -> {len(sources)} source -> "
                "grounded cited answer"
            )
        ),
        evidence=evidence,
    )


def _verify_contrastive_routing(
    *,
    completed_cases: Sequence[CompletedDemoCase],
    advertised_tools: list[object],
) -> StepResult:
    """Verify that distinct questions exercise distinct safe agent routes."""
    started = time.perf_counter()
    failures: list[str] = []
    case_evidence: list[dict[str, Any]] = []
    observed_routes: set[tuple[str, ...]] = set()
    advertised_names = {
        str(item["name"])
        for item in advertised_tools
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }

    for case in completed_cases:
        spec = case.spec
        completed = case.completed
        result = completed.get("result")
        if completed.get("state") != "completed" or not isinstance(result, dict):
            failures.append(f"{spec.scenario_id}: run did not complete with a result")
            result = {}
        if completed.get("scenario_id") != spec.scenario_id:
            failures.append(f"{spec.scenario_id}: response scenario does not match")

        raw_steps = result.get("steps")
        steps = raw_steps if isinstance(raw_steps, list) else []
        tool_steps = [
            item
            for item in steps
            if isinstance(item, dict) and isinstance(item.get("tool_name"), str)
        ]
        selected_tools = tuple(str(item["tool_name"]) for item in tool_steps)
        observed_routes.add(selected_tools)
        if selected_tools != spec.expected_tools:
            failures.append(f"{spec.scenario_id}: unexpected tool route")
        if any(item.get("tool_ok") is not True for item in tool_steps):
            failures.append(f"{spec.scenario_id}: selected tool did not succeed")
        if not set(selected_tools).issubset(advertised_names):
            failures.append(f"{spec.scenario_id}: route used an unadvertised tool")

        trace = result.get("trace")
        trace = trace if isinstance(trace, dict) else {}
        if trace.get("tool_calls") != list(selected_tools):
            failures.append(f"{spec.scenario_id}: steps and trace routes disagree")
        answer_status = result.get("answer_status")
        if answer_status != spec.expected_answer_status:
            failures.append(f"{spec.scenario_id}: unexpected answer status")

        raw_sources = result.get("sources")
        sources = raw_sources if isinstance(raw_sources, list) else []
        if len(sources) != spec.expected_source_count:
            failures.append(f"{spec.scenario_id}: unexpected source count")
        grounding = trace.get("grounding")
        grounding = grounding if isinstance(grounding, dict) else {}
        if (
            grounding.get("has_retrieval_evidence")
            is not spec.expected_retrieval_evidence
        ):
            failures.append(f"{spec.scenario_id}: retrieval evidence mismatch")
        if grounding.get("has_source_citation") is not spec.expected_citation:
            failures.append(f"{spec.scenario_id}: citation state mismatch")

        expected_success = spec.expected_answer_status == "grounded"
        if result.get("success") is not expected_success:
            failures.append(f"{spec.scenario_id}: success state mismatch")
        answer = result.get("answer")
        answer_text = answer if isinstance(answer, str) else ""
        if not answer_text.strip():
            failures.append(f"{spec.scenario_id}: final answer is empty")
        if spec.expected_answer_status == "abstain" and not answer_text.startswith(
            "I cannot provide a grounded answer"
        ):
            failures.append(f"{spec.scenario_id}: unsafe answer was not replaced")
        if spec.scenario_id == "prompt_injection":
            serialized = json.dumps(completed, ensure_ascii=False).casefold()
            if "ignore previous" in serialized or "system prompt" in serialized:
                failures.append("prompt_injection: unsafe content leaked")

        case_evidence.append(
            {
                "scenario_id": spec.scenario_id,
                "question": trace_text(spec.question, max_chars=500),
                "selected_tools": list(selected_tools),
                "source_count": len(sources),
                "answer_status": answer_status,
                "answer": trace_text(answer_text, max_chars=500),
            }
        )

    if len(completed_cases) != len(CONTRAST_CASES):
        failures.append("contrast case set is incomplete")
    if len(observed_routes) != len(completed_cases):
        failures.append("different questions did not produce distinct tool routes")
    observed_statuses = {case.get("answer_status") for case in case_evidence}
    if observed_statuses != {"grounded", "abstain"}:
        failures.append("contrast set lacks grounded and abstain outcomes")

    evidence = {
        "case_count": len(case_evidence),
        "distinct_route_count": len(observed_routes),
        "grounded_count": sum(
            case.get("answer_status") == "grounded" for case in case_evidence
        ),
        "safe_abstention_count": sum(
            case.get("answer_status") == "abstain" for case in case_evidence
        ),
        "cases": case_evidence,
    }
    return StepResult(
        key="contrastive_routing",
        label="Contrastive routing and abstention",
        status="FAIL" if failures else "PASS",
        duration_ms=_elapsed_ms(started),
        summary=(
            _bounded_failure("; ".join(failures))
            if failures
            else (
                f"{len(case_evidence)} questions -> {len(observed_routes)} routes; "
                f"grounded={evidence['grounded_count']}; "
                f"safe_abstain={evidence['safe_abstention_count']}"
            )
        ),
        evidence=evidence,
    )


def _verify_reproducibility_and_tool_args(
    *,
    port: int,
    completed_cases: Sequence[CompletedDemoCase],
    advertised_tools: list[object],
) -> StepResult:
    """Verify deterministic replay, relevant tool args and evidence hashing."""
    started = time.perf_counter()
    failures: list[str] = []
    tool_arg_evidence: list[dict[str, Any]] = []
    advertised_specs = _advertised_tool_specs(advertised_tools)

    if not completed_cases:
        failures.append("no completed cases are available for replay")
        replay_projection_matches = False
        replay_acceptance_matches = False
    else:
        first_case = completed_cases[0]
        replayed = _http_json(
            port,
            "/v1/runs",
            method="POST",
            payload={
                "scenario_id": first_case.spec.scenario_id,
                "question": first_case.spec.question,
            },
            headers={
                "Idempotency-Key": (
                    f"acceptance-commission-{first_case.spec.scenario_id}"
                )
            },
        )
        replay_acceptance_matches = replayed == first_case.accepted
        if not replay_acceptance_matches:
            failures.append("idempotency replay did not return the same acceptance")
        replayed_completed = _http_json(port, str(first_case.accepted["polling_url"]))
        replay_projection_matches = (
            _stable_case_projection(replayed_completed)
            == _stable_case_projection(first_case.completed)
        )
        if not replay_projection_matches:
            failures.append("idempotency replay changed the stable result projection")

    projection_hashes: dict[str, str] = {}
    for case in completed_cases:
        projection = _stable_case_projection(case.completed)
        projection_hashes[case.spec.scenario_id] = _sha256_json(projection)
        result = case.completed.get("result")
        result = result if isinstance(result, dict) else {}
        raw_steps = result.get("steps")
        steps = raw_steps if isinstance(raw_steps, list) else []
        for step in steps:
            if not isinstance(step, dict) or not isinstance(
                step.get("tool_name"), str
            ):
                continue
            tool_name = str(step["tool_name"])
            raw_args = step.get("tool_args")
            tool_args = raw_args if isinstance(raw_args, dict) else {}
            if raw_args is not None and not isinstance(raw_args, dict):
                failures.append(f"{case.spec.scenario_id}: tool args are not objects")
            failures.extend(
                _tool_arg_contract_failures(
                    scenario_id=case.spec.scenario_id,
                    question=case.spec.question,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    advertised_specs=advertised_specs,
                )
            )
            tool_arg_evidence.append(
                {
                    "scenario_id": case.spec.scenario_id,
                    "tool_name": tool_name,
                    "args": _bounded_json_value(tool_args),
                }
            )

    evidence_payload = {
        "case_projection_hashes": projection_hashes,
        "idempotency_replay": {
            "same_accepted_response": replay_acceptance_matches,
            "same_result_projection": replay_projection_matches,
        },
        "tool_args": tool_arg_evidence,
    }
    evidence = {
        **evidence_payload,
        "evidence_payload_sha256": _sha256_json(evidence_payload),
    }
    return StepResult(
        key="reproducibility",
        label="Reproducibility and tool arguments",
        status="FAIL" if failures else "PASS",
        duration_ms=_elapsed_ms(started),
        summary=(
            _bounded_failure("; ".join(failures))
            if failures
            else (
                "idempotency replay stable; tool args relevant and bounded; "
                f"evidence_sha256={evidence['evidence_payload_sha256'][:12]}"
            )
        ),
        evidence=evidence,
    )


def _verify_fail_closed_http(port: int) -> StepResult:
    """Exercise negative HTTP paths through the real localhost API."""
    started = time.perf_counter()
    failures: list[str] = []
    case_evidence: list[dict[str, Any]] = []

    _http_json(
        port,
        "/v1/runs",
        method="POST",
        payload={
            "scenario_id": "grounded_success",
            "question": "conflict baseline",
        },
        headers={"Idempotency-Key": "acceptance-negative-conflict"},
    )
    observations = (
        (
            "idempotency_conflict",
            _http_json_response(
                port,
                "/v1/runs",
                method="POST",
                payload={
                    "scenario_id": "empty_cards",
                    "question": "conflict baseline",
                },
                headers={"Idempotency-Key": "acceptance-negative-conflict"},
            ),
            409,
            "idempotency_conflict",
        ),
        (
            "extra_run_field",
            _http_json_response(
                port,
                "/v1/runs",
                method="POST",
                payload={"scenario_id": "grounded_success", "run_id": "attacker"},
            ),
            422,
            "validation_error",
        ),
        (
            "oversized_payload",
            _http_json_response(
                port,
                "/v1/runs",
                method="POST",
                payload={"scenario_id": "grounded_success", "question": "x" * 5000},
            ),
            413,
            "payload_too_large",
        ),
        (
            "unknown_tool",
            _http_json_response(
                port,
                "/v1/demo/tools/write.grade/call",
                method="POST",
                payload={"args": {}},
            ),
            404,
            "unknown_tool",
        ),
        (
            "forbidden_identity_args",
            _http_json_response(
                port,
                "/v1/demo/tools/rag.search/call",
                method="POST",
                payload={"args": {"query": "photosynthesis", "run_id": "attacker"}},
            ),
            422,
            "forbidden_identity_args",
        ),
        (
            "unknown_run",
            _http_json_response(port, "/v1/runs/acceptance-missing-run"),
            404,
            "unknown_run",
        ),
    )
    for name, observation, expected_status, expected_code in observations:
        error = observation.body.get("error")
        error = error if isinstance(error, dict) else {}
        code = error.get("code")
        if observation.status_code != expected_status:
            failures.append(f"{name}: expected HTTP {expected_status}")
        if code != expected_code:
            failures.append(f"{name}: expected error code {expected_code}")
        serialized = json.dumps(observation.body, ensure_ascii=False)
        if "Traceback" in serialized or "DEMOSECRET" in serialized:
            failures.append(f"{name}: unsafe diagnostic leaked")
        case_evidence.append(
            {
                "case": name,
                "status_code": observation.status_code,
                "error_code": code,
            }
        )

    evidence = {"case_count": len(case_evidence), "cases": case_evidence}
    return StepResult(
        key="fail_closed_http",
        label="Fail-closed HTTP safety",
        status="FAIL" if failures else "PASS",
        duration_ms=_elapsed_ms(started),
        summary=(
            _bounded_failure("; ".join(failures))
            if failures
            else f"{len(case_evidence)} invalid requests returned bounded envelopes"
        ),
        evidence=evidence,
    )


def _source_label(source: object) -> str:
    if not isinstance(source, dict):
        return ""
    for key in ("file_name", "title", "url", "source"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return trace_text(value, max_chars=160)
    return ""


def _wait_for_json(
    process: subprocess.Popen[str], port: int, path: str
) -> dict[str, Any]:
    deadline = time.monotonic() + API_START_TIMEOUT_SEC
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("local API process exited during startup")
        try:
            return _http_json(port, path, timeout=0.5)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"local API startup timed out: {trace_text(last_error)}")


def _http_json_response(
    port: int,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 2.0,
) -> HttpJsonObservation:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://{DEFAULT_HOST}:{port}{path}",
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = int(response.status)
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        raw = exc.read()
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("API response must be a JSON object")
    return HttpJsonObservation(status_code=status_code, body=decoded)


def _http_json(
    port: int,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    observation = _http_json_response(
        port,
        path,
        method=method,
        payload=payload,
        headers=headers,
        timeout=timeout,
    )
    if 200 <= observation.status_code < 300:
        return observation.body
    error = observation.body.get("error")
    error = error if isinstance(error, dict) else {}
    raise RuntimeError(
        f"HTTP {observation.status_code}: {error.get('code') or 'unknown_error'}"
    )


def _advertised_tool_specs(advertised_tools: list[object]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for item in advertised_tools:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        specs[str(item["name"])] = item
    return specs


def _tool_arg_contract_failures(
    *,
    scenario_id: str,
    question: str,
    tool_name: str,
    tool_args: dict[str, Any],
    advertised_specs: dict[str, dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    tool_spec = advertised_specs.get(tool_name)
    if tool_spec is None:
        return [f"{scenario_id}: {tool_name} is not advertised"]
    schema = tool_spec.get("args_schema")
    schema = schema if isinstance(schema, dict) else {}
    required = {
        str(item) for item in schema.get("required", []) if isinstance(item, str)
    }
    properties = schema.get("properties")
    allowed = set(properties) if isinstance(properties, dict) else set()
    missing = sorted(required - set(tool_args))
    extra = sorted(set(tool_args) - allowed) if allowed else []
    if missing:
        failures.append(f"{scenario_id}: {tool_name} missing args {missing}")
    if extra:
        failures.append(f"{scenario_id}: {tool_name} has unexpected args {extra}")
    if _contains_forbidden_key(tool_args):
        failures.append(f"{scenario_id}: {tool_name} exposes harness identity args")

    serialized_args = json.dumps(tool_args, ensure_ascii=False).casefold()
    if "ignore previous" in serialized_args or "system prompt" in serialized_args:
        failures.append(f"{scenario_id}: {tool_name} leaked unsafe prompt text")

    if tool_name == "rag.search":
        query = tool_args.get("query")
        if not isinstance(query, str) or not query.strip():
            failures.append(f"{scenario_id}: rag.search query is empty")
        top_k = tool_args.get("top_k")
        if top_k is not None and (
            not isinstance(top_k, int) or not 1 <= top_k <= 5
        ):
            failures.append(f"{scenario_id}: rag.search top_k is not bounded")
        query_text = query.casefold() if isinstance(query, str) else ""
        if scenario_id == "grounded_success" and not (
            "photosynthesis" in query_text
            and ("glucose" in query_text or "energy" in query_text)
        ):
            failures.append(
                "grounded_success: rag.search query does not match the question"
            )
        if (
            scenario_id == "prompt_injection"
            and query_text != "unsafe synthetic prompt"
        ):
            failures.append(
                "prompt_injection: rag.search query was not safely rewritten"
            )
    if tool_name == "quiz.generate" and scenario_id == "grounded_success":
        topic = tool_args.get("topic")
        mode = tool_args.get("learning_mode")
        if not isinstance(topic, str) or "photosynthesis" not in topic.casefold():
            failures.append("grounded_success: quiz topic does not match the question")
        if mode != "practice":
            failures.append("grounded_success: quiz mode is not practice")
    if tool_name == "cards.get_due":
        limit = tool_args.get("limit")
        if limit is not None and (
            not isinstance(limit, int) or not 1 <= limit <= 10
        ):
            failures.append("empty_cards: cards.get_due limit is not bounded")
    del question
    return failures


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in FORBIDDEN_TOOL_ARG_KEYS:
                return True
            if _contains_forbidden_key(nested):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _stable_case_projection(completed: dict[str, Any]) -> dict[str, Any]:
    result = completed.get("result")
    result = result if isinstance(result, dict) else {}
    raw_steps = result.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    tool_steps = [
        step
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("tool_name"), str)
    ]
    trace = result.get("trace")
    trace = trace if isinstance(trace, dict) else {}
    grounding = trace.get("grounding")
    grounding = grounding if isinstance(grounding, dict) else {}
    sources = result.get("sources")
    sources = sources if isinstance(sources, list) else []
    return {
        "scenario_id": completed.get("scenario_id"),
        "state": completed.get("state"),
        "answer": result.get("answer"),
        "answer_status": result.get("answer_status"),
        "success": result.get("success"),
        "stop_reason": result.get("stop_reason"),
        "selected_tools": [str(step["tool_name"]) for step in tool_steps],
        "tool_args": [
            {
                "tool_name": str(step["tool_name"]),
                "args": (
                    step.get("tool_args")
                    if isinstance(step.get("tool_args"), dict)
                    else {}
                ),
            }
            for step in tool_steps
        ],
        "source_count": len(sources),
        "source_labels": [_source_label(source) for source in sources],
        "grounding": {
            "has_retrieval_evidence": grounding.get("has_retrieval_evidence"),
            "has_source_citation": grounding.get("has_source_citation"),
            "source_count": grounding.get("source_count"),
        },
    }


def _bounded_json_value(value: object) -> object:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(serialized) <= 600:
        return value
    return trace_text(serialized, max_chars=600)


def _sha256_json(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _successful_command_summary(key: str, output: str) -> str:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return trace_text(lines[-1] if lines else "completed")[:240]
    if key == "offline_eval":
        return (
            f"gate_status={payload.get('gate_status')}; "
            f"promotion_status={payload.get('promotion_status')}"
        )
    if key == "mock_profile":
        result = payload.get("result")
        projection = result if isinstance(result, dict) else {}
        return (
            f"success={projection.get('success')}; "
            f"answer_status={projection.get('answer_status')}; "
            f"tools={projection.get('tool_calls')}"
        )
    if key == "scripted_provider":
        return (
            f"mode={payload.get('mode')}; cases={payload.get('case_count')}; "
            f"task_success_rate={payload.get('task_success_rate')}"
        )
    return "completed"


def _build_report(
    *,
    metadata: dict[str, Any],
    steps: Sequence[StepResult],
    full_checks: bool,
    port: int,
    overall_status: str,
) -> dict[str, Any]:
    passed_keys = {step.key for step in steps if step.status == "PASS"}
    profile_by_step = {
        "mock_profile": "mock",
        "local_vector": "local_vector",
        "scripted_provider": "scripted_provider_contract",
    }
    api_status = next(
        (step.status for step in steps if step.key == "mock_api"),
        "NOT_RUN",
    )
    chain_step = next((step for step in steps if step.key == "agentic_chain"), None)
    chain_report: dict[str, Any] = {
        "status": chain_step.status if chain_step is not None else "NOT_RUN",
    }
    if chain_step is not None and chain_step.evidence is not None:
        chain_report.update(chain_step.evidence)
    contrast_step = next(
        (step for step in steps if step.key == "contrastive_routing"),
        None,
    )
    contrast_report: dict[str, Any] = {
        "status": contrast_step.status if contrast_step is not None else "NOT_RUN",
    }
    if contrast_step is not None and contrast_step.evidence is not None:
        contrast_report.update(contrast_step.evidence)
    reproducibility_step = next(
        (step for step in steps if step.key == "reproducibility"),
        None,
    )
    reproducibility_report: dict[str, Any] = {
        "status": (
            reproducibility_step.status
            if reproducibility_step is not None
            else "NOT_RUN"
        ),
    }
    if (
        reproducibility_step is not None
        and reproducibility_step.evidence is not None
    ):
        reproducibility_report.update(reproducibility_step.evidence)
    fail_closed_step = next(
        (step for step in steps if step.key == "fail_closed_http"),
        None,
    )
    fail_closed_report: dict[str, Any] = {
        "status": (
            fail_closed_step.status if fail_closed_step is not None else "NOT_RUN"
        ),
    }
    if fail_closed_step is not None and fail_closed_step.evidence is not None:
        fail_closed_report.update(fail_closed_step.evidence)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "repository": "agent-coach",
        "checked_at_utc": _utc_now(),
        **metadata,
        "mode": "full_offline_acceptance" if full_checks else "offline_acceptance",
        "overall_status": overall_status,
        "api": {
            "bind": f"{DEFAULT_HOST}:{port}",
            "swagger_url": f"http://{DEFAULT_HOST}:{port}/docs",
            "smoke_status": api_status,
            "production_auth": False,
            "state_store": "ephemeral_in_memory",
        },
        "profiles_executed": [
            profile
            for key, profile in profile_by_step.items()
            if key in passed_keys
        ],
        "agentic_chain": chain_report,
        "contrastive_routing": contrast_report,
        "reproducibility": reproducibility_report,
        "fail_closed_http": fail_closed_report,
        "evidence_payload_sha256": reproducibility_report.get(
            "evidence_payload_sha256"
        ),
        "steps": [_step_report(step) for step in steps],
        "limitations": [
            "standalone deterministic diploma demo",
            "offline by default",
            "scripted provider validation is not live provider evidence",
            "no production authentication",
            "no durable production state",
            "no production deployment approval",
        ],
    }


def _port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        try:
            server.bind((DEFAULT_HOST, port))
        except OSError:
            return False
    return True


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _process_failure_details(
    process: subprocess.Popen[str], exc: Exception
) -> str:
    details = str(exc)
    if process.poll() is not None and process.stdout is not None:
        details = f"{details}\n{process.stdout.read()}"
    return _bounded_failure(details)


def _public_command(args: Sequence[str]) -> tuple[str, ...]:
    if not args:
        return ()
    return ("python", *args[1:])


def _bounded_failure(value: object) -> str:
    safe = trace_text(value)
    if len(safe) <= MAX_FAILURE_SUMMARY_CHARS:
        return safe
    return safe[: MAX_FAILURE_SUMMARY_CHARS - 3] + "..."


def _print_step(step: StepResult) -> None:
    print(f"[{step.status}] {step.label}: {step.summary}")
    if step.evidence is None:
        return
    if step.key == "agentic_chain":
        context = step.evidence.get("context")
        context = context if isinstance(context, dict) else {}
        tools = step.evidence.get("selected_tools")
        tool_text = " -> ".join(tools) if isinstance(tools, list) else "none"
        sources = context.get("source_labels")
        source_text = ", ".join(sources) if isinstance(sources, list) else "none"
        print(f"    1. Question: {step.evidence.get('question')}")
        print(f"    2. Tool selection: {tool_text}")
        print(f"    3. Retrieved context: {source_text}")
        print(f"    4. Grounded answer: {step.evidence.get('answer')}")
    elif step.key == "contrastive_routing":
        cases = step.evidence.get("cases")
        if not isinstance(cases, list):
            return
        for case in cases:
            if not isinstance(case, dict):
                continue
            tools = case.get("selected_tools")
            route = " -> ".join(tools) if isinstance(tools, list) else "none"
            print(
                f"    {case.get('scenario_id')}: {case.get('question')} "
                f"-> {route} -> {case.get('answer_status')}"
            )
    elif step.key == "reproducibility":
        replay = step.evidence.get("idempotency_replay")
        replay = replay if isinstance(replay, dict) else {}
        print(
            "    replay: "
            f"accepted={replay.get('same_accepted_response')}; "
            f"projection={replay.get('same_result_projection')}"
        )
        print(
            "    evidence_sha256: "
            f"{step.evidence.get('evidence_payload_sha256')}"
        )
    elif step.key == "fail_closed_http":
        cases = step.evidence.get("cases")
        if not isinstance(cases, list):
            return
        for case in cases:
            if not isinstance(case, dict):
                continue
            print(
                f"    {case.get('case')}: HTTP {case.get('status_code')} "
                f"{case.get('error_code')}"
            )


def _step_report(step: StepResult) -> dict[str, Any]:
    report = asdict(step)
    if report["evidence"] is None:
        del report["evidence"]
    return report


def _git_output(*args: str, fallback: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback


def _is_repo_local(path: Path) -> bool:
    resolved = path.resolve()
    root = REPO_ROOT.resolve()
    return resolved == root or root in resolved.parents


def _port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
