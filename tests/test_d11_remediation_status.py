from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import check_d11_remediation_status as status
from scripts import run_live_eval

HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SESSION = "11111111-1111-4111-8111-111111111111"
OTHER_SESSION = "22222222-2222-4222-8222-222222222222"
FILE_SHA = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
UTC = "2026-08-25T08:15:00Z"


def test_changed_files_must_match_fingerprint_and_status() -> None:
    payload = _complete_package_a()
    payload["changed_files"] = payload["changed_files"][:1]

    failures = status.validate_status(payload)

    assert "changed_files do not match fingerprinted_files" in failures

    missing_status = _complete_package_a()
    missing_status["changed_files"] = [
        item
        for item in missing_status["changed_files"]
        if item["path"] != status.STATUS_FILE
    ]
    missing_failures = status.validate_status(missing_status)

    assert "changed_files must include STATUS_FILE" in missing_failures


def test_promotion_pass_without_git_repo_fails(tmp_path: Path) -> None:
    payload = _promotion_pass_handoff()
    _write_handoff_artifacts(tmp_path, payload)

    failures = status.validate_status(payload, handoff=True, artifact_dir=tmp_path)

    assert "promotion PASS requires git repository" in failures


def test_complete_pass_for_package_a_allows_only_b1() -> None:
    payload = _complete_package_a()

    assert status.validate_status(payload) == []
    assert payload["next_allowed_package"] == "B1"
    assert payload["d11_promotion_status"] == "HOLD"


def test_malformed_package_skip_fails() -> None:
    payload = _complete_package_a()
    payload["current_package"] = "C1"
    payload["last_completed_package"] = "C1"
    payload["next_allowed_package"] = "C2"
    payload["package_ledger"][-1]["package"] = "C1"
    _rehash_ledger(payload)

    failures = status.validate_status(payload)

    assert "package order skipped" in failures


def test_changed_policy_fails() -> None:
    payload = _complete_package_a()
    payload["autonomous_live_policy"] = "BLOCKER"

    failures = status.validate_status(payload)

    assert "autonomous_live_policy changed after initialization" in failures


def test_missing_required_check_fails_complete_pass() -> None:
    payload = _complete_package_a()
    payload["checks_passed"] = [
        item
        for item in payload["checks_passed"]
        if item["id"] != "acceptance_suite"
    ]

    failures = status.validate_status(payload)

    assert "missing required check id" in failures


def test_fingerprint_mismatch_fails() -> None:
    payload = _complete_package_a()
    payload["checkpoint_fingerprint_sha256"] = FILE_SHA

    failures = status.validate_status(payload)

    assert "checkpoint fingerprint does not match declared files" in failures


def test_competing_active_lease_fails() -> None:
    payload = _in_progress_package_a()

    failures = status.validate_lease_acquire(payload, OTHER_SESSION)

    assert "competing ACTIVE lease is present" in failures
    assert status.validate_lease_acquire(payload, SESSION) == []


def test_complete_requires_released_lease() -> None:
    payload = _complete_package_a()
    payload["lease_status"] = "ACTIVE"
    payload["active_session_id"] = SESSION

    failures = status.validate_status(payload)

    assert "COMPLETE requires RELEASED lease" in failures


def test_e2_before_offline_packages_fail() -> None:
    payload = _complete_package_a()
    payload["schema_version"] = status.HANDOFF_SCHEMA_VERSION
    payload["current_package"] = "E2"
    payload["last_completed_package"] = "E2"
    payload["next_allowed_package"] = None
    payload["package_ledger"][-1]["package"] = "E2"
    payload["network_provider_calls"] = 1
    payload["provider_cost_status"] = "incurred"
    _rehash_ledger(payload)
    handoff = _as_handoff(payload)

    failures = status.validate_status(handoff, handoff=True)

    assert "E2 is forbidden before A-E1 COMPLETE+PASS" in failures


def test_promotion_pass_without_e2_fails() -> None:
    payload = _complete_package_a()
    payload["d11_promotion_status"] = "PASS"

    failures = status.validate_status(payload)

    assert "tracked status cannot set d11_promotion_status PASS" in failures


def test_provider_calls_nonzero_for_offline_package_fails() -> None:
    payload = _complete_package_a()
    payload["network_provider_calls"] = 1

    failures = status.validate_status(payload)

    assert "offline package must record zero provider calls" in failures


def test_unknown_field_fails() -> None:
    payload = _complete_package_a()
    payload["unexpected"] = "nope"

    failures = status.validate_status(payload)

    assert "status keys are not the exact schema" in failures


def test_absolute_path_and_hash_chain_fail() -> None:
    payload = _complete_package_a()
    drive = "D"
    payload["exact_resume_instruction"] = f"resume from {drive}:/secret-local-path"
    broken = deepcopy(payload)
    broken["package_ledger"][-1]["entry_sha256"] = FILE_SHA

    path_failures = status.validate_status(payload)
    chain_failures = status.validate_status(broken)

    assert "absolute local path is not allowed" in path_failures
    assert "ledger entry_sha256 is incorrect" in chain_failures


def test_canonical_serialization_mismatch_fails(tmp_path: Path) -> None:
    payload = _complete_package_a()
    path = tmp_path / "status.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    failures = status.validate_status(
        payload,
        expected_bytes=path.read_bytes(),
    )

    assert "status serialization is not canonical" in failures


def test_handoff_mode_rejects_absolute_artifact_path() -> None:
    payload = _valid_e2_handoff()
    payload["artifacts"][0]["filename"] = "../secret.json"

    failures = status.validate_status(payload, handoff=True)

    assert "artifacts is invalid" in failures


def test_cli_returns_nonzero_for_malformed_document(
    tmp_path: Path,
    capsys,
) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}\n", encoding="utf-8")

    code = status.main(["--status", str(path)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.startswith("FAIL: ")
    leaked = chr(68) + ":/" + "Projects"
    assert leaked not in captured.out


def test_cli_rejects_competing_session_on_in_progress(tmp_path: Path) -> None:
    payload = _in_progress_package_a()
    path = tmp_path / "status.json"
    path.write_text(status.serialize_status(payload), encoding="utf-8")

    code = status.main(["--status", str(path), "--session-id", OTHER_SESSION])

    assert code == 1


def test_valid_complete_a_next_package_helper() -> None:
    assert status.next_package("A") == "B1"
    assert status.next_package("E1") == "E2"
    assert status.next_package("E2") is None


def test_rewritten_policy_fails_against_previous_checkpoint() -> None:
    previous = _complete_package_a()
    rewritten = deepcopy(previous)
    rewritten["autonomous_live_policy"] = "BLOCKER"
    for entry in rewritten["package_ledger"]:
        entry["autonomous_live_policy"] = "BLOCKER"
    _rehash_ledger(rewritten)

    failures = status.validate_status(rewritten, previous_status=previous)

    assert "autonomous_live_policy changed from git checkpoint" in failures


def test_rewritten_ledger_entry_fails_append_only() -> None:
    previous = _complete_package_a()
    rewritten = deepcopy(previous)
    rewritten["package_ledger"][0]["evidence_summary"] = "tampered checkpoint summary."
    _rehash_ledger(rewritten)

    failures = status.validate_status(rewritten, previous_status=previous)

    assert "package_ledger is not append-only" in failures


def test_blocker_requires_autonomous_public_wrapper_pair() -> None:
    payload = _valid_e2_handoff()
    payload["autonomous_live_policy"] = "BLOCKER"
    for entry in payload["package_ledger"]:
        entry["autonomous_live_policy"] = "BLOCKER"
    _rehash_ledger(payload)

    failures = status.validate_status(payload, handoff=True)

    assert "BLOCKER policy requires autonomous live public/wrapper pair" in failures


def test_live_artifact_over_64kb_fails() -> None:
    payload = _valid_e2_handoff()
    payload["artifacts"][0]["size_bytes"] = 65000

    failures = status.validate_status(payload, handoff=True)

    assert "handoff artifact exceeds registered size cap" in failures


def test_autonomous_public_without_wrapper_fails() -> None:
    payload = _valid_e2_handoff()
    payload["artifacts"].append(
        {
            "artifact_type": "autonomous_live_public",
            "filename": "autonomous-live-public.json",
            "size_bytes": 32,
            "sha256": FILE_SHA,
        }
    )

    failures = status.validate_status(payload, handoff=True)

    assert "handoff artifact public/wrapper pair is incomplete" in failures


def test_handoff_filler_bytes_are_not_promotion_evidence(tmp_path: Path) -> None:
    payload = _promotion_pass_handoff()
    for item in payload["artifacts"]:
        data = b"x" * int(item["size_bytes"])
        item["sha256"] = hashlib.sha256(data).hexdigest()
        (tmp_path / str(item["filename"])).write_bytes(data)

    failures = status.validate_status(payload, handoff=True, artifact_dir=tmp_path)

    assert "handoff artifact is not JSON" in failures
    assert "promotion PASS requires git repository" in failures


def test_handoff_verifies_size_and_digest(tmp_path: Path) -> None:
    payload = _promotion_pass_handoff()
    _write_handoff_artifacts(tmp_path, payload)
    (tmp_path / str(payload["artifacts"][0]["filename"])).write_bytes(b"tampered")
    failures = status.validate_status(payload, handoff=True, artifact_dir=tmp_path)

    assert "handoff artifact digest does not match file" in failures


def test_handoff_missing_artifact_file_fails(tmp_path: Path) -> None:
    payload = _valid_e2_handoff()

    failures = status.validate_status(payload, handoff=True, artifact_dir=tmp_path)

    assert "handoff artifact file is missing" in failures


def test_package_a_ready_to_commit_survives_clean_commit_without_rewrite(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    docs = repo / "docs"
    tests_dir = repo / "tests"
    scripts_dir = repo / "scripts"
    docs.mkdir()
    tests_dir.mkdir()
    scripts_dir.mkdir()
    plan = docs / "implementation_plan.md"
    plan.write_text("base plan\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "docs/implementation_plan.md")
    _git(repo, "commit", "-m", "base")
    base = _git_text(repo, "rev-parse", "HEAD").strip()

    plan.write_text("package A plan\n", encoding="utf-8", newline="\n")
    acceptance = tests_dir / "test_acceptance_demo.py"
    acceptance.write_text("assert True\n", encoding="utf-8", newline="\n")
    ready = _complete_package_a_for_repo(repo, base_head=base, package="A")
    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, ready)
    before_bytes = status_path.read_bytes()
    assert _validate_status_file(status_path, repo) == []

    b1_too_early = _b1_from_completed_a(ready, resolved_head=base)
    early_failures = status.validate_status(b1_too_early, repo_root=repo)
    assert "unexpected path outside package write-set" in early_failures
    assert status.PREDECESSOR_READY_CHECKPOINT_FAILURE in early_failures

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "package A")
    resolved = _git_text(repo, "rev-parse", "HEAD").strip()

    assert status_path.read_bytes() == before_bytes
    after = status.load_json_object(status_path)
    assert after["checkpoint_commit_state"] == "READY_TO_COMMIT"
    assert after["resolved_completion_commit"] is None
    assert after["observed_head"] == base
    assert _validate_status_file(status_path, repo) == []
    assert status.derived_resolved_completion_commit(repo, after) == resolved

    b1 = _b1_from_completed_a(after, resolved_head=resolved)
    status.write_status_document(status_path, b1)
    assert _validate_status_file(status_path, repo) == []

    false_add = deepcopy(b1)
    for item in false_add["changed_files"]:
        if item["path"] == status.STATUS_FILE:
            item["state"] = "ADD"
    assert "STATUS_FILE state does not match repository" in status.validate_status(
        false_add,
        repo_root=repo,
    )


def test_b1_requires_committed_ready_to_commit_predecessor(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    docs = repo / "docs"
    tests_dir = repo / "tests"
    docs.mkdir()
    tests_dir.mkdir()
    plan = docs / "implementation_plan.md"
    plan.write_text("base plan\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "docs/implementation_plan.md")
    _git(repo, "commit", "-m", "base")
    base = _git_text(repo, "rev-parse", "HEAD").strip()

    plan.write_text("package A plan\n", encoding="utf-8", newline="\n")
    acceptance = tests_dir / "test_acceptance_demo.py"
    acceptance.write_text("assert True\n", encoding="utf-8", newline="\n")
    ready = _complete_package_a_for_repo(repo, base_head=base, package="A")
    head_snapshot = deepcopy(ready)
    head_snapshot["schema_version"] = "agent-coach-d11-remediation-status/1.0.0"
    head_snapshot["checkpoint_commit_state"] = "UNCOMMITTED"
    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, head_snapshot)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "package A without READY_TO_COMMIT")
    resolved = _git_text(repo, "rev-parse", "HEAD").strip()

    b1 = _b1_from_completed_a(ready, resolved_head=resolved)
    status.write_status_document(status_path, b1)
    failures = status.validate_status(b1, repo_root=repo)
    assert status.PREDECESSOR_READY_CHECKPOINT_FAILURE in failures


def test_b1_predecessor_rejects_unexpected_committed_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    docs = repo / "docs"
    tests_dir = repo / "tests"
    docs.mkdir()
    tests_dir.mkdir()
    plan = docs / "implementation_plan.md"
    plan.write_text("base plan\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "docs/implementation_plan.md")
    _git(repo, "commit", "-m", "base")
    base = _git_text(repo, "rev-parse", "HEAD").strip()

    plan.write_text("package A plan\n", encoding="utf-8", newline="\n")
    acceptance = tests_dir / "test_acceptance_demo.py"
    acceptance.write_text("assert True\n", encoding="utf-8", newline="\n")
    ready = _complete_package_a_for_repo(repo, base_head=base, package="A")
    (repo / "unexpected.txt").write_text("not in package A\n", encoding="utf-8")
    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, ready)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "package A with extra file")
    resolved = _git_text(repo, "rev-parse", "HEAD").strip()

    b1 = _b1_from_completed_a(ready, resolved_head=resolved)
    status.write_status_document(status_path, b1)
    failures = status.validate_status(b1, repo_root=repo)

    assert status.PREDECESSOR_READY_CHECKPOINT_FAILURE in failures


def test_clean_ready_checkpoint_verifies_committed_status_file_state(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    docs = repo / "docs"
    docs.mkdir()
    plan = docs / "implementation_plan.md"
    plan.write_text("base plan\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "docs/implementation_plan.md")
    _git(repo, "commit", "-m", "base")
    base = _git_text(repo, "rev-parse", "HEAD").strip()

    plan.write_text("package A plan\n", encoding="utf-8", newline="\n")
    ready = _complete_package_a_for_repo(repo, base_head=base, package="A")
    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, ready)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "package A")

    false_modify = deepcopy(ready)
    for item in false_modify["changed_files"]:
        if item["path"] == status.STATUS_FILE:
            item["state"] = "MODIFY"
    failures = status.validate_status(false_modify, repo_root=repo)

    assert "STATUS_FILE state does not match repository" in failures


def test_b1_predecessor_requires_causal_first_parent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    docs = repo / "docs"
    tests_dir = repo / "tests"
    docs.mkdir()
    tests_dir.mkdir()
    plan = docs / "implementation_plan.md"
    plan.write_text("base plan\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "docs/implementation_plan.md")
    _git(repo, "commit", "-m", "base")
    base = _git_text(repo, "rev-parse", "HEAD").strip()

    plan.write_text("package A plan\n", encoding="utf-8", newline="\n")
    acceptance = tests_dir / "test_acceptance_demo.py"
    acceptance.write_text("assert True\n", encoding="utf-8", newline="\n")
    ready = _complete_package_a_for_repo(repo, base_head=base, package="A")
    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, ready)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "package A")
    _git(repo, "commit", "--allow-empty", "-m", "unrelated")
    drifted = _git_text(repo, "rev-parse", "HEAD").strip()
    after = status.load_json_object(status_path)

    b1 = _b1_from_completed_a(after, resolved_head=drifted)
    status.write_status_document(status_path, b1)
    failures = status.validate_status(b1, repo_root=repo)
    assert status.PREDECESSOR_READY_CHECKPOINT_FAILURE in failures


def test_clean_e1_ready_to_commit_then_e2_handoff_from_disk(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    docs = repo / "docs"
    docs.mkdir()
    plan = docs / "implementation_plan.md"
    plan.write_text("base plan\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "docs/implementation_plan.md")
    _git(repo, "commit", "-m", "base")
    base = _git_text(repo, "rev-parse", "HEAD").strip()

    plan.write_text("package E1 plan\n", encoding="utf-8", newline="\n")
    ready = _e1_ready_to_commit_for_repo(repo, base_head=base)
    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, ready)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "package E1")
    resolved = _git_text(repo, "rev-parse", "HEAD").strip()
    assert _validate_status_file(status_path, repo) == []
    tracked = status.load_json_object(status_path)
    assert tracked["resolved_completion_commit"] is None
    assert status.derived_resolved_completion_commit(repo, tracked) == resolved

    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    handoff = _promotion_pass_handoff()
    handoff["base_head"] = tracked["base_head"]
    handoff["observed_head"] = resolved
    handoff["observed_origin_main"] = resolved
    handoff["resolved_completion_commit"] = resolved
    handoff["autonomous_live_policy"] = tracked["autonomous_live_policy"]
    handoff["current_package"] = "E2"
    handoff["implementation_status"] = "COMPLETE"
    handoff["package_verdict"] = "PASS"
    e2_entry = _ledger_entry(handoff)
    e2_entry["previous_entry_sha256"] = tracked["package_ledger"][-1]["entry_sha256"]
    e2_entry["entry_sha256"] = status.ledger_entry_digest(e2_entry)
    handoff["package_ledger"] = [*tracked["package_ledger"], e2_entry]
    _write_handoff_artifacts(handoff_dir, handoff)
    handoff_path = handoff_dir / "e2-handoff.json"
    status.write_status_document(handoff_path, handoff, handoff=True)
    assert (
        status.validate_status(
            status.load_json_object(handoff_path),
            handoff=True,
            repo_root=repo,
            expected_bytes=handoff_path.read_bytes(),
            artifact_dir=handoff_dir,
        )
        == []
    )

    independent = _promotion_pass_handoff()
    independent["resolved_completion_commit"] = resolved
    _write_handoff_artifacts(handoff_dir, independent)
    independent_failures = status.validate_status(
        independent,
        handoff=True,
        repo_root=repo,
        artifact_dir=handoff_dir,
    )
    assert "package_ledger is not append-only" in independent_failures

    missing_report = deepcopy(handoff)
    missing_report["artifacts"] = [
        item
        for item in missing_report["artifacts"]
        if item["artifact_type"] != "promotion_report"
    ]
    missing = status.validate_status(
        missing_report,
        handoff=True,
        artifact_dir=handoff_dir,
    )
    assert "promotion PASS is missing required evidence artifacts" in missing


def test_old_schema_version_fails() -> None:
    payload = _complete_package_a()
    payload["schema_version"] = "agent-coach-d11-remediation-status/1.0.0"

    failures = status.validate_status(payload)

    assert "unsupported schema_version" in failures


def test_committed_checkpoint_state_is_rejected() -> None:
    payload = _complete_package_a()
    payload["checkpoint_commit_state"] = "COMMITTED_CHECKPOINT"
    payload["resolved_completion_commit"] = HEAD

    failures = status.validate_status(payload)

    assert "checkpoint_commit_state is invalid" in failures


def test_in_progress_hold_allows_released_lease() -> None:
    payload = _in_progress_hold_package_a()

    assert status.validate_status(payload) == []


def test_latest_ledger_entry_can_reopen_package() -> None:
    previous = _complete_package_a()
    reopened = _in_progress_hold_package_a()
    new_entry = _ledger_entry(reopened)
    new_entry["previous_entry_sha256"] = previous["package_ledger"][0]["entry_sha256"]
    new_entry["entry_sha256"] = status.ledger_entry_digest(new_entry)
    reopened["package_ledger"] = [previous["package_ledger"][0], new_entry]

    assert status.validate_status(reopened, previous_status=previous) == []


def test_promotion_pass_without_promotion_report_fails() -> None:
    payload = _promotion_pass_handoff()
    payload["artifacts"] = [
        item
        for item in payload["artifacts"]
        if item["artifact_type"] != "promotion_report"
    ]

    failures = status.validate_status(payload, handoff=True)

    assert "promotion PASS is missing required evidence artifacts" in failures


def test_promotion_pass_requires_frozen_clean_released() -> None:
    dirty = _promotion_pass_handoff()
    dirty["worktree_state"] = "DIRTY_EXPECTED"
    not_frozen = _promotion_pass_handoff()
    not_frozen["checkpoint_commit_state"] = "READY_TO_COMMIT"
    not_frozen["resolved_completion_commit"] = None

    dirty_failures = status.validate_status(dirty, handoff=True)
    frozen_failures = status.validate_status(not_frozen, handoff=True)

    assert "promotion PASS requires CLEAN worktree" in dirty_failures
    assert "promotion PASS requires FROZEN_REVIEWED" in frozen_failures


def test_promotion_artifacts_require_real_current_schemas(tmp_path: Path) -> None:
    payload = _promotion_pass_handoff()
    _write_handoff_artifacts(tmp_path, payload)

    report = tmp_path / "promotion_report.json"
    report.write_text(
        json.dumps(
            {
                "promotion_status": "HOLD",
                "legacy_commit": payload["resolved_completion_commit"],
            }
        ),
        encoding="utf-8",
    )
    for item in payload["artifacts"]:
        if item["artifact_type"] == "promotion_report":
            item["size_bytes"] = report.stat().st_size
            item["sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()

    failures = status.validate_status(
        payload,
        handoff=True,
        artifact_dir=tmp_path,
    )

    assert "promotion report schema_version is invalid" in failures
    assert "promotion report commit does not match resolved commit" in failures
    assert "promotion report promotion_status is not PASS" in failures


def test_promotion_artifacts_reject_semantically_empty_json(tmp_path: Path) -> None:
    payload = _promotion_pass_handoff()
    for item in payload["artifacts"]:
        artifact_type = str(item["artifact_type"])
        if artifact_type == "forced_live_public":
            data = {"schema_version": "agent-coach-live-eval-public/1.0.0"}
        elif artifact_type == "forced_live_wrapper":
            data = {
                "schema_version": "agent-coach-live-eval-evidence/1.0.0",
                "commit": payload["resolved_completion_commit"],
            }
        elif artifact_type == "clean_release":
            data = {"commit": payload["resolved_completion_commit"]}
        else:
            data = {
                "schema_version": "agent-coach-diploma-eval-report/1.0.0",
                "repository": "agent-coach",
                "commit": payload["resolved_completion_commit"],
                "git_available": True,
                "worktree_dirty": False,
                "gate_status": "PASS",
                "promotion_status": "PASS",
                "threshold_failures": [],
                "promotion_blockers": [],
                "live_evidence": {"status": "available"},
                "clean_release_evidence": {"status": "available"},
            }
        encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
        item["size_bytes"] = len(encoded)
        item["sha256"] = hashlib.sha256(encoded).hexdigest()
        (tmp_path / str(item["filename"])).write_bytes(encoded)

    failures = status.validate_status(
        payload,
        handoff=True,
        artifact_dir=tmp_path,
    )

    assert "live public live eval case registry is missing" in failures
    assert "live wrapper provenance is invalid" in failures
    assert "clean release commands are invalid" in failures
    assert "promotion report live_evidence commit mismatch" in failures


def test_promotion_pass_requires_clean_git_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    docs = repo / "docs"
    docs.mkdir()
    plan = docs / "implementation_plan.md"
    plan.write_text("base plan\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "docs/implementation_plan.md")
    _git(repo, "commit", "-m", "base")
    base = _git_text(repo, "rev-parse", "HEAD").strip()

    plan.write_text("package E1 plan\n", encoding="utf-8", newline="\n")
    ready = _e1_ready_to_commit_for_repo(repo, base_head=base)
    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, ready)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "package E1")
    resolved = _git_text(repo, "rev-parse", "HEAD").strip()
    tracked = status.load_json_object(status_path)

    handoff = _promotion_pass_handoff()
    handoff["base_head"] = tracked["base_head"]
    handoff["observed_head"] = resolved
    handoff["observed_origin_main"] = resolved
    handoff["resolved_completion_commit"] = resolved
    handoff["autonomous_live_policy"] = tracked["autonomous_live_policy"]
    e2_entry = _ledger_entry(handoff)
    e2_entry["previous_entry_sha256"] = tracked["package_ledger"][-1]["entry_sha256"]
    e2_entry["entry_sha256"] = status.ledger_entry_digest(e2_entry)
    handoff["package_ledger"] = [*tracked["package_ledger"], e2_entry]
    _write_handoff_artifacts(tmp_path, handoff)
    plan.write_text("dirty after E2 handoff\n", encoding="utf-8", newline="\n")

    failures = status.validate_status(
        handoff,
        handoff=True,
        repo_root=repo,
        artifact_dir=tmp_path,
    )

    assert "promotion PASS requires clean git worktree" in failures


def test_promotion_pass_requires_valid_committed_e1_checkpoint(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    docs = repo / "docs"
    docs.mkdir()
    plan = docs / "implementation_plan.md"
    plan.write_text("base plan\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "docs/implementation_plan.md")
    _git(repo, "commit", "-m", "base")
    base = _git_text(repo, "rev-parse", "HEAD").strip()

    plan.write_text("package E1 plan\n", encoding="utf-8", newline="\n")
    ready = _e1_ready_to_commit_for_repo(repo, base_head=base)
    ready["checkpoint_fingerprint_sha256"] = FILE_SHA
    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, ready)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "invalid package E1")
    resolved = _git_text(repo, "rev-parse", "HEAD").strip()
    tracked = status.load_json_object(status_path)

    handoff = _promotion_pass_handoff()
    handoff["base_head"] = tracked["base_head"]
    handoff["observed_head"] = resolved
    handoff["observed_origin_main"] = resolved
    handoff["resolved_completion_commit"] = resolved
    handoff["autonomous_live_policy"] = tracked["autonomous_live_policy"]
    e2_entry = _ledger_entry(handoff)
    e2_entry["previous_entry_sha256"] = tracked["package_ledger"][-1]["entry_sha256"]
    e2_entry["entry_sha256"] = status.ledger_entry_digest(e2_entry)
    handoff["package_ledger"] = [*tracked["package_ledger"], e2_entry]
    _write_handoff_artifacts(tmp_path, handoff)

    failures = status.validate_status(
        handoff,
        handoff=True,
        repo_root=repo,
        artifact_dir=tmp_path,
    )

    assert "promotion PASS requires valid committed E1 checkpoint" in failures


def test_promotion_pass_without_artifact_dir_fails() -> None:
    payload = _promotion_pass_handoff()

    failures = status.validate_status(payload, handoff=True)

    assert "promotion PASS requires verified artifact files" in failures


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Package A Test",
            "-c",
            "user.email=dev@example.test",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_text(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _b1_from_completed_a(
    completed_a: dict[str, Any],
    *,
    resolved_head: str,
) -> dict[str, Any]:
    b1 = deepcopy(completed_a)
    b1["current_package"] = "B1"
    b1["implementation_status"] = "IN_PROGRESS"
    b1["package_verdict"] = "NOT_RUN"
    b1["lease_status"] = "ACTIVE"
    b1["active_session_id"] = SESSION
    b1["last_completed_package"] = "A"
    b1["next_allowed_package"] = "B1"
    b1["checkpoint_commit_state"] = "UNCOMMITTED"
    b1["resolved_completion_commit"] = None
    b1["base_head"] = resolved_head
    b1["observed_head"] = resolved_head
    b1["observed_origin_main"] = resolved_head
    b1["worktree_state"] = "DIRTY_EXPECTED"
    b1["checks_passed"] = []
    b1["fingerprinted_files"] = []
    b1["changed_files"] = [
        {
            "path": status.STATUS_FILE,
            "purpose": "Start package B1 from committed Package A.",
            "state": "MODIFY",
        }
    ]
    b1["checkpoint_fingerprint_sha256"] = status.fingerprint_sha256(
        base_head=resolved_head,
        files=[],
    )
    b1_entry = _ledger_entry(b1)
    b1_entry["previous_entry_sha256"] = completed_a["package_ledger"][-1][
        "entry_sha256"
    ]
    b1_entry["entry_sha256"] = status.ledger_entry_digest(b1_entry)
    b1["package_ledger"] = [*completed_a["package_ledger"], b1_entry]
    return b1


def _complete_package_a_for_repo(
    repo: Path,
    *,
    base_head: str,
    package: str,
) -> dict[str, Any]:
    observed = status.observe_worktree(
        repo,
        base_head=base_head,
        package=package,
    )
    payload = _complete_package_a()
    payload["base_head"] = base_head
    payload["observed_head"] = observed["head"]
    payload["observed_origin_main"] = observed["origin_main"]
    payload["fingerprinted_files"] = observed["fingerprinted_files"]
    payload["checkpoint_fingerprint_sha256"] = observed[
        "checkpoint_fingerprint_sha256"
    ]
    payload["changed_files"] = _changed_files_from_fingerprint(
        observed["fingerprinted_files"],
        status_state="ADD",
    )
    payload["package_ledger"] = [_ledger_entry(payload)]
    return payload


def _complete_package_a() -> dict[str, Any]:
    files = [
        {
            "path": "docs/implementation_plan.md",
            "sha256": FILE_SHA,
            "state": "MODIFY",
        }
    ]
    checks = [
        {
            "id": check_id,
            "command": f"python -m pytest {check_id}",
            "platform": "win32/Windows",
            "result": "PASS",
        }
        for check_id in status.PACKAGE_REQUIRED_CHECKS["A"]
    ]
    payload = _base_payload(
        implementation_status="COMPLETE",
        package_verdict="PASS",
        lease_status="RELEASED",
        active_session_id=None,
        last_completed_package="A",
        next_allowed_package="B1",
        blockers=[],
        checks_passed=checks,
        fingerprinted_files=files,
    )
    payload["checkpoint_commit_state"] = "READY_TO_COMMIT"
    payload["checkpoint_fingerprint_sha256"] = status.fingerprint_sha256(
        base_head=HEAD,
        files=files,
    )
    payload["package_ledger"] = [_ledger_entry(payload)]
    return payload


def _in_progress_package_a() -> dict[str, Any]:
    files = [
        {
            "path": "scripts/check_d11_remediation_status.py",
            "sha256": FILE_SHA,
            "state": "ADD",
        }
    ]
    payload = _base_payload(
        implementation_status="IN_PROGRESS",
        package_verdict="NOT_RUN",
        lease_status="ACTIVE",
        active_session_id=SESSION,
        last_completed_package=None,
        next_allowed_package="A",
        blockers=[],
        checks_passed=[],
        fingerprinted_files=files,
    )
    payload["checkpoint_fingerprint_sha256"] = status.fingerprint_sha256(
        base_head=HEAD,
        files=files,
    )
    payload["package_ledger"] = [_ledger_entry(payload)]
    return payload


def _base_payload(
    *,
    implementation_status: str,
    package_verdict: str,
    lease_status: str,
    active_session_id: str | None,
    last_completed_package: str | None,
    next_allowed_package: str | None,
    blockers: list[str],
    checks_passed: list[dict[str, str]],
    fingerprinted_files: list[dict[str, str]],
) -> dict[str, Any]:
    payload = {
        "schema_version": status.STATUS_SCHEMA_VERSION,
        "updated_at_utc": UTC,
        "autonomous_live_policy": "DOCUMENTED_LIMITATION",
        "base_head": HEAD,
        "observed_head": HEAD,
        "observed_origin_main": HEAD,
        "resolved_completion_commit": None,
        "checkpoint_commit_state": "UNCOMMITTED",
        "checkpoint_fingerprint_sha256": FILE_SHA,
        "fingerprinted_files": fingerprinted_files,
        "worktree_state": "DIRTY_EXPECTED",
        "active_session_id": active_session_id,
        "session_started_at_utc": UTC,
        "lease_status": lease_status,
        "current_package": "A",
        "implementation_status": implementation_status,
        "package_verdict": package_verdict,
        "d11_promotion_status": "HOLD",
        "network_provider_calls": 0,
        "provider_cost_status": "zero",
        "changed_files": _changed_files_from_fingerprint(fingerprinted_files),
        "checks_passed": checks_passed,
        "checks_not_run": ["full_pytest_suite", "live_provider_eval"],
        "remaining_risks": [
            "Windows acceptance flake is not claimed eliminated without a "
            "reproduced cause."
        ],
        "blockers": blockers,
        "last_completed_package": last_completed_package,
        "next_allowed_package": next_allowed_package,
        "exact_resume_instruction": (
            "Start WORK_PACKAGE=B1 after OWNER_APPROVAL; D11 promotion stays HOLD."
        ),
        "package_ledger": [],
    }
    return payload


def _ledger_entry(payload: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "package": payload["current_package"],
        "status": payload["implementation_status"],
        "verdict": payload["package_verdict"],
        "observed_head": payload["observed_head"],
        "completed_at_utc": payload["updated_at_utc"],
        "evidence_summary": "Package A checkpoint for focused tests.",
        "autonomous_live_policy": payload["autonomous_live_policy"],
        "previous_entry_sha256": None,
        "entry_sha256": "0" * 64,
    }
    entry["entry_sha256"] = status.ledger_entry_digest(entry)
    return entry


def _rehash_ledger(payload: dict[str, Any]) -> None:
    previous = None
    for entry in payload["package_ledger"]:
        entry["previous_entry_sha256"] = previous
        entry["entry_sha256"] = status.ledger_entry_digest(entry)
        previous = entry["entry_sha256"]


def _as_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    artifacts = [
        {
            "artifact_type": "forced_live_public",
            "filename": "live-eval-public.json",
            "size_bytes": 12,
            "sha256": FILE_SHA,
        }
    ]
    handoff: dict[str, Any] = {}
    for key in status.HANDOFF_KEYS:
        if key == "artifacts":
            handoff[key] = artifacts
        else:
            handoff[key] = payload[key]
    handoff["schema_version"] = status.HANDOFF_SCHEMA_VERSION
    return handoff


def _valid_e2_handoff() -> dict[str, Any]:
    payload = _complete_package_a()
    payload["schema_version"] = status.HANDOFF_SCHEMA_VERSION
    payload["current_package"] = "E2"
    payload["last_completed_package"] = "E2"
    payload["next_allowed_package"] = None
    payload["checkpoint_commit_state"] = "FROZEN_REVIEWED"
    payload["worktree_state"] = "CLEAN"
    payload["network_provider_calls"] = 2
    payload["provider_cost_status"] = "incurred"
    payload["checks_passed"] = [
        {
            "id": check_id,
            "command": f"python scripts/{check_id}.py",
            "platform": "win32/Windows",
            "result": "PASS",
        }
        for check_id in status.PACKAGE_REQUIRED_CHECKS["E2"]
    ]
    payload["current_package"] = "E1"
    offline_entries = []
    previous = None
    for package in status.OFFLINE_PACKAGES:
        payload["current_package"] = package
        payload["implementation_status"] = "COMPLETE"
        payload["package_verdict"] = "PASS"
        entry = _ledger_entry(payload)
        entry["previous_entry_sha256"] = previous
        entry["entry_sha256"] = status.ledger_entry_digest(entry)
        offline_entries.append(entry)
        previous = entry["entry_sha256"]
    payload["current_package"] = "E2"
    payload["implementation_status"] = "COMPLETE"
    payload["package_verdict"] = "PASS"
    payload["checkpoint_commit_state"] = "FROZEN_REVIEWED"
    payload["worktree_state"] = "CLEAN"
    payload["resolved_completion_commit"] = HEAD
    e2_entry = _ledger_entry(payload)
    e2_entry["previous_entry_sha256"] = previous
    e2_entry["entry_sha256"] = status.ledger_entry_digest(e2_entry)
    payload["package_ledger"] = [*offline_entries, e2_entry]
    handoff = _as_handoff(payload)
    handoff["artifacts"] = [
        {
            "artifact_type": artifact_type,
            "filename": f"{artifact_type}.json",
            "size_bytes": 32,
            "sha256": FILE_SHA,
        }
        for artifact_type in (
            "forced_live_public",
            "forced_live_wrapper",
            "clean_release",
            "promotion_report",
        )
    ]
    return handoff


def _promotion_pass_handoff() -> dict[str, Any]:
    payload = _valid_e2_handoff()
    payload["d11_promotion_status"] = "PASS"
    return payload


def _in_progress_hold_package_a() -> dict[str, Any]:
    payload = _in_progress_package_a()
    payload["package_verdict"] = "HOLD"
    payload["lease_status"] = "RELEASED"
    payload["active_session_id"] = None
    payload["package_ledger"] = [_ledger_entry(payload)]
    return payload


def _validate_status_file(path: Path, repo: Path) -> list[str]:
    return status.validate_status(
        status.load_json_object(path),
        repo_root=repo,
        expected_bytes=path.read_bytes(),
    )


def _changed_files_from_fingerprint(
    files: list[dict[str, str]],
    *,
    purpose: str = "package A artifact",
    status_state: str = "MODIFY",
) -> list[dict[str, str]]:
    items = [
        {
            "path": item["path"],
            "purpose": purpose,
            "state": item["state"],
        }
        for item in files
    ]
    items.append(
        {
            "path": status.STATUS_FILE,
            "purpose": purpose,
            "state": status_state,
        }
    )
    items.sort(key=lambda item: item["path"])
    return items


def _minimal_artifact_payload(
    artifact_type: str,
    resolved_commit: str,
    *,
    public_digest: str | None = None,
    public_payload: dict[str, Any] | None = None,
    clean_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if artifact_type == "promotion_report":
        case_count = public_payload["case_count"] if public_payload else 5
        task_success_rate = (
            public_payload["task_success_rate"] if public_payload else 1.0
        )
        public_record = {
            "label": "docs/evidence/live-eval-public.json",
            "sha256": public_digest or FILE_SHA,
        }
        clean_commands = status._project_clean_release_commands(
            clean_payload.get("commands") if clean_payload else None
        ) or _clean_release_command_records()
        return {
            "schema_version": "agent-coach-diploma-eval-report/1.0.0",
            "repository": "agent-coach",
            "commit": resolved_commit,
            "git_available": True,
            "worktree_dirty": False,
            "gate_status": "PASS",
            "promotion_status": "PASS",
            "threshold_failures": [],
            "promotion_blockers": [],
            "live_evidence": {
                "status": "available",
                "required_for_promotion": True,
                "task_success_rate": task_success_rate,
                "case_count": case_count,
                "commit": resolved_commit,
                "profile": "live_provider",
                "provider_profile_opt_in": True,
                "checked_at_utc": UTC,
                "evidence_artifacts": [public_record],
                "provenance": status.EXPECTED_LIVE_EVIDENCE_PROVENANCE,
                "evidence_schema_version": "agent-coach-live-eval-evidence/1.0.0",
            },
            "clean_release_evidence": {
                "status": "available",
                "required_for_promotion": True,
                "commit": resolved_commit,
                "checked_at_utc": UTC,
                "commands": clean_commands,
                "provenance": status.EXPECTED_CLEAN_RELEASE_EVIDENCE_PROVENANCE,
                "evidence_schema_version": (
                    "agent-coach-clean-release-evidence/1.0.0"
                ),
            },
        }
    if artifact_type in {"forced_live_public", "autonomous_live_public"}:
        payload = run_live_eval.run_live_eval(scripted=True)
        payload["mode"] = "live_provider"
        payload["contains_scripted_responses"] = False
        payload["provider_profile_opt_in"] = True
        payload["checked_at_utc"] = UTC
        return payload
    if artifact_type in {"forced_live_wrapper", "autonomous_live_wrapper"}:
        case_count = public_payload["case_count"] if public_payload else 5
        task_success_rate = (
            public_payload["task_success_rate"] if public_payload else 1.0
        )
        return {
            "schema_version": "agent-coach-live-eval-evidence/1.0.0",
            "provenance": status.EXPECTED_LIVE_EVIDENCE_PROVENANCE,
            "commit": resolved_commit,
            "profile": "live_provider",
            "provider_profile_opt_in": True,
            "checked_at_utc": UTC,
            "case_count": case_count,
            "task_success_rate": task_success_rate,
            "evidence_artifacts": [
                {
                    "label": "docs/evidence/live-eval-public.json",
                    "sha256": public_digest or FILE_SHA,
                }
            ],
        }
    return {
        "schema_version": "agent-coach-clean-release-evidence/1.0.0",
        "provenance": status.EXPECTED_CLEAN_RELEASE_EVIDENCE_PROVENANCE,
        "commit": resolved_commit,
        "worktree_dirty": False,
        "checked_at_utc": UTC,
        "commands": _clean_release_command_records(),
    }


def _clean_release_command_records() -> dict[str, dict[str, object]]:
    return {
        command_id: {
            "command": command,
            "exit_code": 0,
            "status": "PASS",
            "stdout_sha256": FILE_SHA,
        }
        for command_id, command in status.EXPECTED_CLEAN_RELEASE_COMMANDS.items()
    }


def _write_handoff_artifacts(directory: Path, payload: dict[str, Any]) -> None:
    resolved = str(payload["resolved_completion_commit"])
    digest_by_type: dict[str, str] = {}
    payload_by_type: dict[str, dict[str, Any]] = {}
    for item in payload["artifacts"]:
        artifact_type = str(item["artifact_type"])
        if artifact_type.endswith("_wrapper"):
            continue
        public_payload = payload_by_type.get(
            "forced_live_public",
            payload_by_type.get("autonomous_live_public"),
        )
        clean_payload = payload_by_type.get("clean_release")
        data = json.dumps(
            _minimal_artifact_payload(
                artifact_type,
                resolved,
                public_digest=digest_by_type.get("forced_live_public"),
                public_payload=public_payload,
                clean_payload=clean_payload,
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        item["size_bytes"] = len(data)
        item["sha256"] = hashlib.sha256(data).hexdigest()
        digest_by_type[artifact_type] = str(item["sha256"])
        payload_by_type[artifact_type] = json.loads(data.decode("utf-8"))
        (directory / str(item["filename"])).write_bytes(data)
    for item in payload["artifacts"]:
        artifact_type = str(item["artifact_type"])
        if not artifact_type.endswith("_wrapper"):
            continue
        public_type = (
            "forced_live_public"
            if artifact_type == "forced_live_wrapper"
            else "autonomous_live_public"
        )
        data = json.dumps(
            _minimal_artifact_payload(
                artifact_type,
                resolved,
                public_digest=digest_by_type.get(public_type),
                public_payload=payload_by_type.get(public_type),
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        item["size_bytes"] = len(data)
        item["sha256"] = hashlib.sha256(data).hexdigest()
        (directory / str(item["filename"])).write_bytes(data)


def _e1_ready_to_commit_for_repo(repo: Path, *, base_head: str) -> dict[str, Any]:
    observed = status.observe_worktree(
        repo,
        base_head=base_head,
        package="E1",
    )
    payload = _complete_package_a()
    payload["current_package"] = "E1"
    payload["last_completed_package"] = "E1"
    payload["next_allowed_package"] = "E2"
    payload["checkpoint_commit_state"] = "READY_TO_COMMIT"
    payload["base_head"] = base_head
    payload["observed_head"] = observed["head"]
    payload["observed_origin_main"] = observed["origin_main"]
    payload["fingerprinted_files"] = observed["fingerprinted_files"]
    payload["checkpoint_fingerprint_sha256"] = observed[
        "checkpoint_fingerprint_sha256"
    ]
    payload["changed_files"] = _changed_files_from_fingerprint(
        observed["fingerprinted_files"],
        purpose="package E1 artifact",
        status_state="ADD",
    )
    payload["checks_passed"] = [
        {
            "id": check_id,
            "command": f"python -m pytest {check_id}",
            "platform": "win32/Windows",
            "result": "PASS",
        }
        for check_id in status.PACKAGE_REQUIRED_CHECKS["E1"]
    ]
    payload["exact_resume_instruction"] = (
        "Start E2 from the derived clean HEAD; do not edit tracked status."
    )
    offline_entries = []
    previous = None
    for package in status.OFFLINE_PACKAGES:
        payload["current_package"] = package
        payload["implementation_status"] = "COMPLETE"
        payload["package_verdict"] = "PASS"
        entry = _ledger_entry(payload)
        entry["previous_entry_sha256"] = previous
        entry["entry_sha256"] = status.ledger_entry_digest(entry)
        offline_entries.append(entry)
        previous = entry["entry_sha256"]
    payload["current_package"] = "E1"
    payload["package_ledger"] = offline_entries
    return payload
