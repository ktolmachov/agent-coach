from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from scripts.run_eval_gate import main

from agent_coach.eval import (
    build_tool_sop_markdown,
    gate,
    load_eval_suite,
    run_eval_suite,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_d11_eval_suite_freezes_thresholds_and_case_count() -> None:
    suite = load_eval_suite()
    categories = {case["category"] for case in suite["cases"]}

    assert suite["schema_version"] == "agent-coach-diploma-eval/1.0.0"
    assert 20 <= len(suite["cases"]) <= 30
    assert suite["thresholds"]["offline_golden_pass_rate"] == 1.0
    assert suite["thresholds"]["retrieval_top1_min_accuracy"] >= 0.8
    assert {
        "retrieval",
        "no_answer",
        "ambiguous_query",
        "multi_step_study_session",
        "quiz_cards_branch",
        "tool_validation",
        "timeout",
        "rate_limit",
        "dependency_failure",
        "cost_step_limit",
        "prompt_injection",
        "fake_secret",
        "pii_private_path",
        "unknown_tool",
        "malformed_native_call",
    } <= categories


def test_d11_eval_gate_passes_offline_and_reports_promotion_hold() -> None:
    report = run_eval_suite()

    assert report["schema_version"] == "agent-coach-diploma-eval-report/1.0.0"
    assert report["gate_status"] == "PASS"
    assert report["promotion_status"] == "HOLD"
    assert report["live_evidence"]["status"] == "unavailable"
    assert report["clean_release_evidence"]["status"] == "unavailable"
    assert "live_evidence_unavailable" in report["promotion_blockers"]
    assert "clean_release_evidence_unavailable" in report["promotion_blockers"]
    assert report["metrics"]["offline_golden_pass_rate"] == 1.0
    assert report["metrics"]["retrieval_top1_accuracy"] >= 0.8
    assert report["metrics"]["invalid_unknown_tool_executions"] == 0
    assert report["metrics"]["security_assertion_failures"] == 0
    assert report["metrics"]["hidden_writes"] == 0
    assert report["metrics"]["grounded_answers_without_citation"] == 0
    assert report["threshold_failures"] == []


def test_live_evidence_is_schema_validated_and_thresholded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = tmp_path / "malformed-live.json"
    malformed.write_text(
        json.dumps({"schema_version": "wrong", "task_success_rate": 1.0}),
        encoding="utf-8",
    )
    malformed_report = run_eval_suite(live_evidence_path=malformed)
    assert malformed_report["gate_status"] == "PASS"
    assert malformed_report["promotion_status"] == "HOLD"
    assert malformed_report["live_evidence"]["status"] == "invalid"
    assert "live_evidence_invalid" in malformed_report["promotion_blockers"]

    weak = tmp_path / "weak-live.json"
    weak.write_text(
        json.dumps(
            {
                "schema_version": "agent-coach-live-eval-evidence/1.0.0",
                "commit": "clean-head",
                "profile": "live_provider",
                "provider_profile_opt_in": True,
                "checked_at_utc": "2026-08-24T00:00:00Z",
                "case_count": 5,
                "task_success_rate": 0.79,
                "evidence_artifacts": ["docs/evidence/live-eval-public.json"],
            }
        ),
        encoding="utf-8",
    )

    def fake_git(*args: str) -> str:
        return "clean-head" if args == ("rev-parse", "HEAD") else ""

    monkeypatch.setattr("agent_coach.eval.gate._git_output", fake_git)
    weak_report = run_eval_suite(live_evidence_path=weak)
    assert weak_report["gate_status"] == "HOLD"
    assert "live_task_success_rate" in weak_report["threshold_failures"]


def test_dirty_worktree_prevents_promotion_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = tmp_path / "live.json"
    live.write_text(
        json.dumps(
            {
                "schema_version": "agent-coach-live-eval-evidence/1.0.0",
                "commit": "clean-head",
                "profile": "live_provider",
                "provider_profile_opt_in": True,
                "checked_at_utc": "2026-08-24T00:00:00Z",
                "case_count": 5,
                "task_success_rate": 0.8,
                "evidence_artifacts": ["docs/evidence/live-eval-public.json"],
            }
        ),
        encoding="utf-8",
    )
    clean = tmp_path / "clean.json"
    clean.write_text(
        json.dumps(
            {
                "schema_version": "agent-coach-clean-release-evidence/1.0.0",
                "commit": "clean-head",
                "worktree_dirty": False,
                "checked_at_utc": "2026-08-24T00:00:00Z",
                "commands": {
                    "fresh_clone_suite": {
                        "command": "python -m pytest",
                        "exit_code": 0,
                        "status": "PASS",
                    },
                    "public_release_gate": {
                        "command": "python scripts/check_public_release.py",
                        "exit_code": 0,
                        "status": "PASS",
                    },
                    "offline_eval_gate": {
                        "command": "python scripts/run_eval_gate.py",
                        "exit_code": 0,
                        "status": "PASS",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_git(*args: str) -> str:
        return "clean-head" if args == ("rev-parse", "HEAD") else " M README.md"

    monkeypatch.setattr("agent_coach.eval.gate._git_output", fake_git)

    report = run_eval_suite(
        live_evidence_path=live,
        clean_release_evidence_path=clean,
    )

    assert report["gate_status"] == "PASS"
    assert report["promotion_status"] == "HOLD"
    assert "worktree_dirty" in report["promotion_blockers"]


def test_clean_promotion_requires_clean_release_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = tmp_path / "live.json"
    live.write_text(
        json.dumps(
            {
                "schema_version": "agent-coach-live-eval-evidence/1.0.0",
                "commit": "clean-head",
                "profile": "live_provider",
                "provider_profile_opt_in": True,
                "checked_at_utc": "2026-08-24T00:00:00Z",
                "case_count": 5,
                "task_success_rate": 0.8,
                "evidence_artifacts": ["docs/evidence/live-eval-public.json"],
            }
        ),
        encoding="utf-8",
    )

    def fake_git(*args: str) -> str:
        return "clean-head" if args == ("rev-parse", "HEAD") else ""

    monkeypatch.setattr("agent_coach.eval.gate._git_output", fake_git)
    report = run_eval_suite(live_evidence_path=live)

    assert report["gate_status"] == "PASS"
    assert report["promotion_status"] == "HOLD"
    assert "clean_release_evidence_unavailable" in report["promotion_blockers"]


def test_minimal_evidence_files_do_not_promote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = tmp_path / "minimal-live.json"
    live.write_text(
        json.dumps(
            {
                "schema_version": "agent-coach-live-eval-evidence/1.0.0",
                "task_success_rate": 1.0,
            }
        ),
        encoding="utf-8",
    )
    clean = tmp_path / "minimal-clean.json"
    clean.write_text(
        json.dumps(
            {
                "schema_version": "agent-coach-clean-release-evidence/1.0.0",
                "commit": "clean-head",
                "worktree_dirty": False,
                "fresh_clone_suite_passed": True,
                "public_release_gate_passed": True,
                "offline_eval_gate_passed": True,
            }
        ),
        encoding="utf-8",
    )

    def fake_git(*args: str) -> str:
        return "clean-head" if args == ("rev-parse", "HEAD") else ""

    monkeypatch.setattr("agent_coach.eval.gate._git_output", fake_git)

    report = run_eval_suite(live_evidence_path=live)

    assert report["gate_status"] == "PASS"
    assert report["promotion_status"] == "HOLD"
    assert "live_evidence_invalid" in report["promotion_blockers"]

    report = run_eval_suite(
        live_evidence_path=_valid_live_evidence(tmp_path),
        clean_release_evidence_path=clean,
    )

    assert report["gate_status"] == "PASS"
    assert report["promotion_status"] == "HOLD"
    assert "clean_release_evidence_invalid" in report["promotion_blockers"]


def test_malformed_suite_thresholds_and_category_labels_fail_closed(
    tmp_path: Path,
) -> None:
    suite = load_eval_suite()
    bad_thresholds = deepcopy(suite)
    bad_thresholds["thresholds"]["retrieval_top1_min_accuracy"] = 0.9
    bad_threshold_path = _write_suite(tmp_path, bad_thresholds, "bad-threshold.json")

    with pytest.raises(ValueError, match="frozen KPI"):
        load_eval_suite(bad_threshold_path)

    array_path = tmp_path / "array.json"
    array_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_eval_suite(array_path)

    label_only = deepcopy(suite)
    for case in label_only["cases"]:
        if case["id"] == "security-pii-private-path-redaction":
            case["type"] = "mock_scenario"
            case["scenario_id"] = "fake_secret"
            case["expected"] = {
                "stop_reason": "completed",
                "answer_status": "abstain",
                "tool_calls": ["rag.search"],
                "source_count": 1,
            }
            break
    label_only_path = _write_suite(tmp_path, label_only, "label-only.json")
    with pytest.raises(ValueError, match="pii_private_path"):
        load_eval_suite(label_only_path)


def test_retrieval_threshold_boundary_is_measured(tmp_path: Path) -> None:
    suite = load_eval_suite()
    at_boundary = deepcopy(suite)
    _corrupt_retrieval_cases(at_boundary, count=2)
    at_boundary_report = run_eval_suite(
        suite_path=_write_suite(tmp_path, at_boundary, "at-boundary.json")
    )

    assert at_boundary_report["metrics"]["retrieval_top1_accuracy"] == 0.8
    assert at_boundary_report["metrics"]["offline_golden_pass_rate"] == 1.0
    assert at_boundary_report["gate_status"] == "PASS"
    assert "retrieval_top1_accuracy" not in at_boundary_report["threshold_failures"]

    below_boundary = deepcopy(suite)
    _corrupt_retrieval_cases(below_boundary, count=3)
    below_report = run_eval_suite(
        suite_path=_write_suite(tmp_path, below_boundary, "below-boundary.json")
    )

    assert below_report["metrics"]["retrieval_top1_accuracy"] == 0.7
    assert below_report["gate_status"] == "HOLD"
    assert "retrieval_top1_accuracy" in below_report["threshold_failures"]


def test_eval_case_exceptions_redact_private_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_path = "D:" + "\\".join(("", "Projects", "hometutor", "private.md"))

    def fail_with_private_path(_scenario_id: str) -> object:
        raise ValueError(f"failed to read {private_path}")

    monkeypatch.setattr(gate, "build_mock_composition", fail_with_private_path)

    result = gate._evaluate_case(
        {
            "id": "leaky",
            "type": "mock_scenario",
            "category": "pii_private_path",
            "scenario_id": "grounded_success",
        }
    )

    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert result["passed"] is False
    assert private_path not in encoded
    assert "hometutor" not in encoded.casefold()


def test_eval_gate_cli_writes_report(tmp_path: Path, capsys) -> None:
    output = tmp_path / "eval_report.json"

    assert main(["--output", str(output)]) == 0

    stdout = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == stdout
    assert written["gate_status"] == "PASS"
    assert written["case_count"] == len(written["results"])


def test_tool_sop_snapshot_matches_generated_markdown() -> None:
    expected = (REPO_ROOT / "docs" / "tool_sop.md").read_text(encoding="utf-8")

    assert build_tool_sop_markdown() == expected
    assert "None optional" not in expected
    assert "integer or null optional" in expected
    assert '{"max_result_chars":' not in expected
    assert "Declared tool limits:" in expected


def _valid_live_evidence(tmp_path: Path) -> Path:
    path = tmp_path / "valid-live.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "agent-coach-live-eval-evidence/1.0.0",
                "commit": "clean-head",
                "profile": "live_provider",
                "provider_profile_opt_in": True,
                "checked_at_utc": "2026-08-24T00:00:00Z",
                "case_count": 5,
                "task_success_rate": 1.0,
                "evidence_artifacts": ["docs/evidence/live-eval-public.json"],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_suite(tmp_path: Path, suite: dict[str, object], name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(suite), encoding="utf-8")
    return path


def _corrupt_retrieval_cases(suite: dict[str, object], *, count: int) -> None:
    changed = 0
    for case in suite["cases"]:
        if case["type"] != "retrieval_top1":
            continue
        case["expected_chunk_id"] = "missing-chunk"
        changed += 1
        if changed == count:
            return
    raise AssertionError("not enough retrieval cases to corrupt")
