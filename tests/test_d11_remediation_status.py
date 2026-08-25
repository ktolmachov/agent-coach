from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import check_d11_remediation_status as status

HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SESSION = "11111111-1111-4111-8111-111111111111"
OTHER_SESSION = "22222222-2222-4222-8222-222222222222"
FILE_SHA = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
UTC = "2026-08-25T08:15:00Z"


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


def test_handoff_verifies_size_and_digest(tmp_path: Path) -> None:
    payload = _valid_e2_handoff()
    for item in payload["artifacts"]:
        data = b"x" * int(item["size_bytes"])
        item["sha256"] = hashlib.sha256(data).hexdigest()
        (tmp_path / str(item["filename"])).write_bytes(data)

    assert status.validate_status(payload, handoff=True, artifact_dir=tmp_path) == []

    (tmp_path / str(payload["artifacts"][0]["filename"])).write_bytes(b"tampered")
    failures = status.validate_status(payload, handoff=True, artifact_dir=tmp_path)

    assert "handoff artifact digest does not match file" in failures


def test_handoff_missing_artifact_file_fails(tmp_path: Path) -> None:
    payload = _valid_e2_handoff()

    failures = status.validate_status(payload, handoff=True, artifact_dir=tmp_path)

    assert "handoff artifact file is missing" in failures


def test_package_a_uncommitted_commit_validate_start_b1(tmp_path: Path) -> None:
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
    uncommitted = _complete_package_a_for_repo(repo, base_head=base, package="A")
    assert status.validate_status(uncommitted, repo_root=repo) == []

    b1_too_early = _b1_from_completed_a(uncommitted, resolved_head=base)
    early_failures = status.validate_status(b1_too_early, repo_root=repo)
    assert "unexpected path outside package write-set" in early_failures

    status_path = repo / status.STATUS_FILE
    status.write_status_document(status_path, uncommitted)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "package A")
    resolved = _git_text(repo, "rev-parse", "HEAD").strip()

    after_commit_failures = status.validate_status(uncommitted, repo_root=repo)
    assert after_commit_failures

    committed = deepcopy(uncommitted)
    committed["checkpoint_commit_state"] = "COMMITTED_CHECKPOINT"
    committed["resolved_completion_commit"] = resolved
    committed["observed_head"] = resolved
    committed["observed_origin_main"] = resolved
    committed["worktree_state"] = "CLEAN"
    observed = status.observe_committed_diff(
        repo,
        base_head=base,
        resolved_commit=resolved,
        package="A",
    )
    committed["fingerprinted_files"] = observed["fingerprinted_files"]
    committed["checkpoint_fingerprint_sha256"] = observed[
        "checkpoint_fingerprint_sha256"
    ]
    extra = _ledger_entry(committed)
    extra["previous_entry_sha256"] = committed["package_ledger"][-1]["entry_sha256"]
    extra["entry_sha256"] = status.ledger_entry_digest(extra)
    committed["package_ledger"] = [*uncommitted["package_ledger"], extra]
    status.write_status_document(status_path, committed)
    committed["worktree_state"] = "DIRTY_EXPECTED"
    assert status.validate_status(committed, repo_root=repo) == []

    b1 = _b1_from_completed_a(committed, resolved_head=resolved)
    status.write_status_document(status_path, b1)
    assert status.validate_status(b1, repo_root=repo) == []


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
    b1["observed_head"] = completed_a["observed_head"]
    b1["observed_origin_main"] = completed_a["observed_origin_main"]
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
    payload["changed_files"] = [
        {
            "path": item["path"],
            "purpose": "package A artifact",
            "state": item["state"],
        }
        for item in observed["fingerprinted_files"]
    ]
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
        "changed_files": [
            {
                "path": item["path"],
                "purpose": "package A artifact",
                "state": item["state"],
            }
            for item in fingerprinted_files
        ],
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
