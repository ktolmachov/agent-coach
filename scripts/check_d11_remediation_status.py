"""Validate the D11 remediation inter-session status ledger.

The checker is offline, fail-closed and never rewrites the checkpoint. It
accepts the tracked status file by default and a separate E2 handoff document
outside the checkout when ``--handoff`` is supplied.

Tracked checkpoints never store the commit they will be committed into.
``READY_TO_COMMIT`` snapshots keep ``resolved_completion_commit`` null; after a
clean commit the validator binds HEAD from Git without editing the file.
``FROZEN_REVIEWED`` and the resolved commit belong to the external E2 wrapper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agent_coach.eval.live_evidence import validate_live_eval_public_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = REPO_ROOT / "docs" / "d11_remediation_status.json"
STATUS_SCHEMA_VERSION = "agent-coach-d11-remediation-status/2.0.0"
HANDOFF_SCHEMA_VERSION = "agent-coach-d11-e2-handoff/2.0.0"
DELETED_CONTENT_SHA256 = hashlib.sha256(
    b"agent-coach-d11-fingerprint:DELETED"
).hexdigest()
PACKAGES = ("A", "B1", "B2", "C1", "C2", "D0", "D1", "D2", "E1", "E2")
OFFLINE_PACKAGES = PACKAGES[:-1]
IMPLEMENTATION_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "COMPLETE", "BLOCKED")
PACKAGE_VERDICTS = ("NOT_RUN", "PASS", "HOLD", "BLOCKED")
PROMOTION_STATUSES = ("HOLD", "PASS", "BLOCKED")
CHECKPOINT_COMMIT_STATES = (
    "UNCOMMITTED",
    "READY_TO_COMMIT",
    "FROZEN_REVIEWED",
)
WORKTREE_STATES = ("CLEAN", "DIRTY_EXPECTED")
LEASE_STATUSES = ("ACTIVE", "STALE_CANDIDATE", "RELEASED")
FILE_STATES = ("ADD", "MODIFY", "DELETE")
POLICIES = ("BLOCKER", "DOCUMENTED_LIMITATION")
COST_STATUSES = ("zero", "not_run", "incurred")
CHECK_RESULTS = ("PASS",)
HANDOFF_ARTIFACT_TYPES = (
    "forced_live_public",
    "forced_live_wrapper",
    "autonomous_live_public",
    "autonomous_live_wrapper",
    "clean_release",
    "promotion_report",
)
EVAL_REPORT_SCHEMA_VERSION = "agent-coach-diploma-eval-report/1.0.0"
LIVE_EVAL_PUBLIC_SCHEMA_VERSION = "agent-coach-live-eval-public/1.0.0"
LIVE_EVAL_WRAPPER_SCHEMA_VERSION = "agent-coach-live-eval-evidence/1.0.0"
CLEAN_RELEASE_EVIDENCE_SCHEMA_VERSION = (
    "agent-coach-clean-release-evidence/1.0.0"
)
EXPECTED_LIVE_EVIDENCE_PROVENANCE = {
    "classification": "redacted_live_provider_eval",
    "contains_credentials": False,
    "contains_learner_data": False,
    "contains_hometutor_runtime_dependency": False,
}
EXPECTED_CLEAN_RELEASE_EVIDENCE_PROVENANCE = {
    "classification": "clean_release_review_evidence",
    "contains_credentials": False,
    "contains_learner_data": False,
    "contains_hometutor_runtime_dependency": False,
}
EXPECTED_CLEAN_RELEASE_COMMANDS = {
    "fresh_clone_suite": "python -m pytest",
    "public_release_gate": "python scripts/check_public_release.py --release",
    "offline_eval_gate": "python scripts/run_eval_gate.py",
}
LIVE_EVIDENCE_MAX_BYTES = 64000
PROMOTION_REPORT_MAX_BYTES = 128000
ARTIFACT_SIZE_CAPS = {
    "forced_live_public": LIVE_EVIDENCE_MAX_BYTES,
    "forced_live_wrapper": LIVE_EVIDENCE_MAX_BYTES,
    "autonomous_live_public": LIVE_EVIDENCE_MAX_BYTES,
    "autonomous_live_wrapper": LIVE_EVIDENCE_MAX_BYTES,
    "clean_release": LIVE_EVIDENCE_MAX_BYTES,
    "promotion_report": PROMOTION_REPORT_MAX_BYTES,
}
ARTIFACT_PAIRS = (
    ("forced_live_public", "forced_live_wrapper"),
    ("autonomous_live_public", "autonomous_live_wrapper"),
)
UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
REPO_PATH_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")
BASENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ABSOLUTE_PATH_RE = (
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    re.compile(r"(?<![:/])/(?:home|Users|opt|var|tmp|mnt|etc|private|root)/"),
)
STATUS_FILE = "docs/d11_remediation_status.json"
MAX_DIAGNOSTIC_CHARS = 240
MAX_PRINTED_FAILURES = 12
MAX_STRING_CHARS = {
    "purpose": 240,
    "evidence_summary": 400,
    "exact_resume_instruction": 800,
    "command": 400,
    "platform": 80,
    "id": 80,
    "reason": 240,
}
STATUS_KEYS = (
    "schema_version",
    "updated_at_utc",
    "autonomous_live_policy",
    "base_head",
    "observed_head",
    "observed_origin_main",
    "resolved_completion_commit",
    "checkpoint_commit_state",
    "checkpoint_fingerprint_sha256",
    "fingerprinted_files",
    "worktree_state",
    "active_session_id",
    "session_started_at_utc",
    "lease_status",
    "current_package",
    "implementation_status",
    "package_verdict",
    "d11_promotion_status",
    "network_provider_calls",
    "provider_cost_status",
    "changed_files",
    "checks_passed",
    "checks_not_run",
    "remaining_risks",
    "blockers",
    "last_completed_package",
    "next_allowed_package",
    "exact_resume_instruction",
    "package_ledger",
)
HANDOFF_KEYS = (
    "schema_version",
    "updated_at_utc",
    "autonomous_live_policy",
    "base_head",
    "observed_head",
    "observed_origin_main",
    "resolved_completion_commit",
    "checkpoint_commit_state",
    "worktree_state",
    "active_session_id",
    "session_started_at_utc",
    "lease_status",
    "current_package",
    "implementation_status",
    "package_verdict",
    "d11_promotion_status",
    "network_provider_calls",
    "provider_cost_status",
    "artifacts",
    "checks_passed",
    "checks_not_run",
    "remaining_risks",
    "blockers",
    "last_completed_package",
    "next_allowed_package",
    "exact_resume_instruction",
    "package_ledger",
)
CHANGED_FILE_KEYS = ("path", "purpose", "state")
FINGERPRINT_FILE_KEYS = ("path", "sha256", "state")
CHECK_KEYS = ("id", "command", "platform", "result")
LEDGER_KEYS = (
    "package",
    "status",
    "verdict",
    "observed_head",
    "completed_at_utc",
    "evidence_summary",
    "autonomous_live_policy",
    "previous_entry_sha256",
    "entry_sha256",
)
ARTIFACT_KEYS = ("artifact_type", "filename", "size_bytes", "sha256")
PACKAGE_WRITE_SETS: dict[str, frozenset[str]] = {
    "A": frozenset(
        {
            "docs/implementation_plan.md",
            "scripts/run_acceptance_demo.py",
            "tests/test_acceptance_demo.py",
            "docs/review_kit.md",
            "scripts/README.md",
            STATUS_FILE,
            "scripts/check_d11_remediation_status.py",
            "tests/test_d11_remediation_status.py",
            "docs/prompts/d11_remediation_implementation_prompt.md",
        }
    ),
    "B1": frozenset(
        {
            "src/agent_coach/eval/live_evidence.py",
            "scripts/run_live_eval.py",
            "tests/test_live_eval_runner.py",
            "tests/test_public_release_gate.py",
            "scripts/check_public_release.py",
            "docs/evidence/live-eval-public.json",
            "docs/eval_gate.md",
            "docs/review_kit.md",
            "docs/implementation_plan.md",
            "README.md",
            STATUS_FILE,
        }
    ),
    "B2": frozenset(
        {
            "scripts/run_live_eval.py",
            "src/agent_coach/eval/gate.py",
            "tests/test_live_eval_runner.py",
            "tests/test_eval_gate.py",
            "docs/eval_gate.md",
            "docs/implementation_plan.md",
            STATUS_FILE,
        }
    ),
    "C1": frozenset(
        {
            "README.md",
            "docs/eval_gate.md",
            "docs/live_profile.md",
            "docs/review_kit.md",
            "docs/implementation_plan.md",
            "src/agent_coach/eval/gate.py",
            "docs/tool_sop.md",
            "tests/test_eval_gate.py",
            STATUS_FILE,
        }
    ),
    "C2": frozenset(
        {
            ".github/workflows/ci.yml",
            "AGENTS.md",
            "README.md",
            "CONTRIBUTING.md",
            "docs/review_kit.md",
            "docs/release_checklist.md",
            "tests/test_public_release_gate.py",
            STATUS_FILE,
        }
    ),
    "D0": frozenset(
        {
            "docs/implementation_plan.md",
            "tests/test_eval_gate.py",
            STATUS_FILE,
        }
    ),
    "D1": frozenset(
        {
            "/".join(("src", "agent_coach", "data", "diploma_eval_cases.json")),
            "src/agent_coach/eval/gate.py",
            "tests/test_eval_gate.py",
            STATUS_FILE,
        }
    ),
    "D2": frozenset(
        {
            "src/agent_coach/eval/gate.py",
            "tests/test_eval_gate.py",
            "docs/eval_gate.md",
            "README.md",
            "docs/implementation_plan.md",
            "scripts/check_public_release.py",
            "tests/test_public_release_gate.py",
            STATUS_FILE,
        }
    ),
    "E1": frozenset(
        {
            "src/agent_coach/eval/gate.py",
            "tests/test_eval_gate.py",
            "tests/test_live_eval_runner.py",
            "scripts/run_live_eval.py",
            "docs/eval_gate.md",
            "docs/implementation_plan.md",
            STATUS_FILE,
        }
    ),
    "E2": frozenset(),
}
PACKAGE_WRITE_PREFIXES: dict[str, tuple[str, ...]] = {
    "B1": ("docs/evidence/",),
    "D0": ("tests/eval_discovery/", "fixtures/eval_discovery/"),
    "E1": ("src/agent_coach/eval/",),
}
PACKAGE_REQUIRED_CHECKS: dict[str, tuple[str, ...]] = {
    "A": (
        "acceptance_suite",
        "status_validator_suite",
        "status_validator_cli",
        "localhost_acceptance_repeats",
        "ruff_touched_python",
        "compileall_touched_python",
        "public_release",
        "git_diff_check",
        "commit_resume_lifecycle",
        "e1_e2_clean_promotion_lifecycle",
    ),
    "B1": (
        "live_registry_suite",
        "historical_classification_suite",
        "public_release",
    ),
    "B2": ("provenance_negative_suite", "promotion_gate_suite"),
    "C1": ("tool_sop_snapshot", "public_release"),
    "C2": ("ci_workflow_suite", "public_release"),
    "D0": ("eval_v2_discovery_report",),
    "D1": ("eval_v2_suite",),
    "D2": ("eval_gate_cli", "public_release"),
    "E1": ("autonomous_harness_suite",),
    "E2": (
        "forced_live_artifact",
        "clean_release_evidence",
        "promotion_gate",
        "handoff_validator",
    ),
}


class StatusValidationError(RuntimeError):
    """Raised when the status document cannot be loaded."""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the D11 remediation status checkpoint."
    )
    parser.add_argument(
        "--status",
        default=str(STATUS_PATH),
        help="Tracked status JSON path relative to the repository root.",
    )
    parser.add_argument(
        "--handoff",
        help="External E2 handoff JSON path. Mutually exclusive with --status.",
    )
    parser.add_argument(
        "--session-id",
        help="Reject a competing ACTIVE lease unless it matches this UUID.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args([] if argv is None else argv)
    try:
        if args.handoff:
            handoff_path = Path(args.handoff)
            payload = load_json_object(handoff_path)
            failures = validate_status(
                payload,
                handoff=True,
                repo_root=REPO_ROOT,
                expected_bytes=handoff_path.read_bytes(),
                artifact_dir=handoff_path.parent,
            )
        else:
            status_path = Path(args.status)
            if not status_path.is_absolute():
                status_path = REPO_ROOT / status_path
            payload = load_json_object(status_path)
            failures = validate_status(
                payload,
                repo_root=REPO_ROOT,
                expected_bytes=status_path.read_bytes(),
            )
        if args.session_id:
            failures.extend(validate_lease_acquire(payload, args.session_id))
    except (OSError, json.JSONDecodeError, StatusValidationError) as exc:
        failures = [_bounded_diagnostic(str(exc))]
    unique: list[str] = []
    for item in failures:
        if item not in unique:
            unique.append(item)
    if unique:
        for item in unique[:MAX_PRINTED_FAILURES]:
            print(f"FAIL: {item}")
        if len(unique) > MAX_PRINTED_FAILURES:
            print(f"FAIL: {len(unique) - MAX_PRINTED_FAILURES} more validation errors")
        return 1
    label = "E2 handoff" if args.handoff else "D11 remediation status"
    print(f"OK: {label} passed")
    return 0


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StatusValidationError("cannot read status document") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StatusValidationError(f"malformed JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise StatusValidationError("status document must be a JSON object")
    return payload


def serialize_status(payload: Mapping[str, Any], *, handoff: bool = False) -> str:
    ordered = order_mapping(payload, HANDOFF_KEYS if handoff else STATUS_KEYS)
    return json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"


def order_mapping(value: Any, keys: Sequence[str]) -> Any:
    if not isinstance(value, dict):
        return value
    ordered: dict[str, Any] = {}
    for key in keys:
        if key not in value:
            continue
        item = value[key]
        if key == "changed_files" and isinstance(item, list):
            ordered[key] = [order_mapping(entry, CHANGED_FILE_KEYS) for entry in item]
        elif key == "fingerprinted_files" and isinstance(item, list):
            ordered[key] = [
                order_mapping(entry, FINGERPRINT_FILE_KEYS) for entry in item
            ]
        elif key == "checks_passed" and isinstance(item, list):
            ordered[key] = [order_mapping(entry, CHECK_KEYS) for entry in item]
        elif key == "package_ledger" and isinstance(item, list):
            ordered[key] = [order_mapping(entry, LEDGER_KEYS) for entry in item]
        elif key == "artifacts" and isinstance(item, list):
            ordered[key] = [order_mapping(entry, ARTIFACT_KEYS) for entry in item]
        else:
            ordered[key] = item
    return ordered


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def ledger_entry_digest(entry: Mapping[str, Any]) -> str:
    payload = {key: entry[key] for key in LEDGER_KEYS if key != "entry_sha256"}
    return sha256_json(payload)


def fingerprint_manifest(
    *,
    base_head: str,
    files: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    ordered_files = sorted(
        (
            {
                "path": str(item["path"]),
                "sha256": str(item["sha256"]),
                "state": str(item["state"]),
            }
            for item in files
        ),
        key=lambda item: item["path"],
    )
    return {"base_head": base_head, "files": ordered_files}


def fingerprint_sha256(
    *,
    base_head: str,
    files: Sequence[Mapping[str, str]],
) -> str:
    return sha256_json(fingerprint_manifest(base_head=base_head, files=files))


def validate_lease_acquire(payload: Mapping[str, Any], session_id: str) -> list[str]:
    failures: list[str] = []
    if not UUID_RE.fullmatch(session_id):
        failures.append("session-id is not a UUID")
        return failures
    if payload.get("lease_status") != "ACTIVE":
        return failures
    current = payload.get("active_session_id")
    if current != session_id:
        failures.append("competing ACTIVE lease is present")
    return failures


def validate_status(
    payload: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
    expected_bytes: bytes | None = None,
    handoff: bool = False,
    artifact_dir: Path | None = None,
    previous_status: Mapping[str, Any] | None = None,
) -> list[str]:
    failures: list[str] = []
    keys = HANDOFF_KEYS if handoff else STATUS_KEYS
    schema = HANDOFF_SCHEMA_VERSION if handoff else STATUS_SCHEMA_VERSION
    actual_keys = tuple(payload.keys())
    if actual_keys != keys:
        failures.append("status keys are not the exact schema")
        return failures
    if payload.get("schema_version") != schema:
        failures.append("unsupported schema_version")
    failures.extend(_validate_common_fields(payload, handoff=handoff))
    if handoff:
        failures.extend(_validate_handoff_fields(payload, artifact_dir=artifact_dir))
    else:
        failures.extend(_validate_tracked_fields(payload))
    failures.extend(_validate_strings_and_paths(payload))
    previous = previous_status
    if previous is None and repo_root is not None:
        previous = load_previous_status(repo_root)
    failures.extend(
        _validate_ledger(payload, handoff=handoff, previous_status=previous)
    )
    failures.extend(
        _validate_package_transition(payload, handoff=handoff, repo_root=repo_root)
    )
    failures.extend(_validate_lease_snapshot(payload, handoff=handoff))
    failures.extend(_validate_required_checks(payload, handoff=handoff))
    failures.extend(_validate_offline_cost(payload, handoff=handoff))
    failures.extend(
        _validate_promotion(
            payload,
            handoff=handoff,
            artifact_dir=artifact_dir,
            repo_root=repo_root,
            previous_status=previous,
        )
    )
    if expected_bytes is not None:
        serialized = serialize_status(payload, handoff=handoff).encode("utf-8")
        if expected_bytes != serialized:
            failures.append("status serialization is not canonical")
    if repo_root is not None and not handoff:
        failures.extend(_validate_against_repository(payload, repo_root))
    return failures


def observe_worktree(
    repo_root: Path,
    *,
    base_head: str,
    package: str,
) -> dict[str, Any]:
    head = _git_output(repo_root, "rev-parse", "HEAD").strip()
    origin = _git_output(repo_root, "rev-parse", "origin/main", check=False)
    origin_main = origin.stdout.strip() if origin.returncode == 0 else head
    changed_paths = _git_status_paths(repo_root)
    changed_file_states = _git_status_file_states(repo_root)
    unexpected = tuple(
        path for path in changed_paths if not _path_allowed(package, path)
    )
    files = _fingerprint_worktree_files(
        repo_root,
        base_head=base_head,
        package=package,
        changed_paths=changed_paths,
    )
    return {
        "head": head,
        "origin_main": origin_main,
        "changed_paths": changed_paths,
        "changed_file_states": changed_file_states,
        "unexpected_paths": unexpected,
        "fingerprinted_files": files,
        "checkpoint_fingerprint_sha256": fingerprint_sha256(
            base_head=base_head,
            files=files,
        ),
    }


def observe_committed_diff(
    repo_root: Path,
    *,
    base_head: str,
    resolved_commit: str,
    package: str,
) -> dict[str, Any]:
    output = _git_output(
        repo_root,
        "diff",
        "--name-status",
        "--no-renames",
        base_head,
        resolved_commit,
    )
    files: list[dict[str, str]] = []
    changed_paths: list[str] = []
    changed_file_states: dict[str, str] = {}
    unexpected: list[str] = []
    for line in output.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        code, raw_path = line.split("\t", 1)
        path = raw_path.strip().replace("\\", "/")
        if not path:
            continue
        changed_paths.append(path)
        state = _diff_status_to_state(code)
        if state is not None:
            changed_file_states[path] = state
        if path == STATUS_FILE:
            continue
        if not _path_allowed(package, path):
            unexpected.append(path)
            continue
        if state is None:
            unexpected.append(path)
            continue
        if state == "DELETE":
            digest = DELETED_CONTENT_SHA256
        else:
            digest = hashlib.sha256(
                _git_blob(repo_root, resolved_commit, path)
            ).hexdigest()
        files.append({"path": path, "sha256": digest, "state": state})
    files.sort(key=lambda item: item["path"])
    return {
        "changed_paths": tuple(dict.fromkeys(changed_paths)),
        "changed_file_states": changed_file_states,
        "unexpected_paths": tuple(dict.fromkeys(unexpected)),
        "fingerprinted_files": files,
        "checkpoint_fingerprint_sha256": fingerprint_sha256(
            base_head=base_head,
            files=files,
        ),
    }


def observe_checkpoint(
    repo_root: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    package = str(payload["current_package"])
    base_head = str(payload["base_head"])
    worktree = observe_worktree(
        repo_root,
        base_head=base_head,
        package=package,
    )
    commit_state = payload.get("checkpoint_commit_state")
    if commit_state != "READY_TO_COMMIT" or worktree["changed_paths"]:
        return {
            **worktree,
            "derived_resolved_completion_commit": None,
            "first_parent": None,
        }
    committed = observe_committed_diff(
        repo_root,
        base_head=base_head,
        resolved_commit=str(worktree["head"]),
        package=package,
    )
    return {
        **worktree,
        "fingerprinted_files": committed["fingerprinted_files"],
        "checkpoint_fingerprint_sha256": committed["checkpoint_fingerprint_sha256"],
        "unexpected_paths": tuple(
            dict.fromkeys(
                [*committed["unexpected_paths"], *worktree["unexpected_paths"]]
            )
        ),
        "committed_paths": committed["changed_paths"],
        "committed_file_states": committed["changed_file_states"],
        "derived_resolved_completion_commit": worktree["head"],
        "first_parent": _first_parent(repo_root),
    }


def derived_resolved_completion_commit(
    repo_root: Path,
    payload: Mapping[str, Any],
) -> str | None:
    """Return the Git-bound completion commit without editing tracked JSON."""
    observed = observe_checkpoint(repo_root, payload)
    return observed.get("derived_resolved_completion_commit")


def load_previous_status(
    repo_root: Path,
    ref: str = "HEAD",
) -> dict[str, Any] | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{STATUS_FILE}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StatusValidationError("git checkpoint status is malformed") from exc
    if not isinstance(payload, dict):
        raise StatusValidationError("git checkpoint status is malformed")
    return payload


def write_status_document(
    path: Path,
    payload: Mapping[str, Any],
    *,
    handoff: bool = False,
) -> None:
    path.write_text(
        serialize_status(payload, handoff=handoff),
        encoding="utf-8",
        newline="\n",
    )


def next_package(package: str) -> str | None:
    try:
        index = PACKAGES.index(package)
    except ValueError:
        return None
    if index + 1 >= len(PACKAGES):
        return None
    return PACKAGES[index + 1]


def _validate_common_fields(payload: Mapping[str, Any], *, handoff: bool) -> list[str]:
    failures: list[str] = []
    for key in (
        "updated_at_utc",
        "session_started_at_utc",
    ):
        if not _utc(payload.get(key)):
            failures.append(f"{key} is not a UTC timestamp")
    for key in ("base_head", "observed_head", "observed_origin_main"):
        if not _commit(payload.get(key)):
            failures.append(f"{key} is not a 40-character commit")
    resolved = payload.get("resolved_completion_commit")
    if resolved is not None and not _commit(resolved):
        failures.append("resolved_completion_commit is invalid")
    if payload.get("autonomous_live_policy") not in POLICIES:
        failures.append("autonomous_live_policy is invalid")
    commit_state = payload.get("checkpoint_commit_state")
    if commit_state not in CHECKPOINT_COMMIT_STATES:
        failures.append("checkpoint_commit_state is invalid")
    elif commit_state in {"UNCOMMITTED", "READY_TO_COMMIT"} and resolved is not None:
        failures.append(f"{commit_state} cannot set resolved_completion_commit")
    elif commit_state == "FROZEN_REVIEWED" and not _commit(resolved):
        failures.append("FROZEN_REVIEWED requires resolved_completion_commit")
    if not handoff and commit_state == "FROZEN_REVIEWED":
        failures.append("tracked status cannot use FROZEN_REVIEWED")
    if payload.get("worktree_state") not in WORKTREE_STATES:
        failures.append("worktree_state is invalid")
    if payload.get("lease_status") not in LEASE_STATUSES:
        failures.append("lease_status is invalid")
    if payload.get("current_package") not in PACKAGES:
        failures.append("current_package is invalid")
    if payload.get("implementation_status") not in IMPLEMENTATION_STATUSES:
        failures.append("implementation_status is invalid")
    if payload.get("package_verdict") not in PACKAGE_VERDICTS:
        failures.append("package_verdict is invalid")
    if payload.get("d11_promotion_status") not in PROMOTION_STATUSES:
        failures.append("d11_promotion_status is invalid")
    if payload.get("provider_cost_status") not in COST_STATUSES:
        failures.append("provider_cost_status is invalid")
    if not _non_negative_int(payload.get("network_provider_calls")):
        failures.append("network_provider_calls is invalid")
    last_completed = payload.get("last_completed_package")
    if last_completed is not None and last_completed not in PACKAGES:
        failures.append("last_completed_package is invalid")
    next_allowed = payload.get("next_allowed_package")
    if next_allowed is not None and next_allowed not in PACKAGES:
        failures.append("next_allowed_package is invalid")
    if not isinstance(payload.get("exact_resume_instruction"), str):
        failures.append("exact_resume_instruction is invalid")
    elif len(payload["exact_resume_instruction"]) > MAX_STRING_CHARS[
        "exact_resume_instruction"
    ]:
        failures.append("exact_resume_instruction exceeds bound")
    if not _string_list(payload.get("remaining_risks")):
        failures.append("remaining_risks is invalid")
    if not _string_list(payload.get("blockers")):
        failures.append("blockers is invalid")
    if not _string_list(payload.get("checks_not_run")):
        failures.append("checks_not_run is invalid")
    if not _check_list(payload.get("checks_passed")):
        failures.append("checks_passed is invalid")
    if not handoff and not _changed_file_list(payload.get("changed_files")):
        failures.append("changed_files is invalid")
    return failures


def _validate_tracked_fields(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if not SHA256_RE.fullmatch(str(payload.get("checkpoint_fingerprint_sha256") or "")):
        failures.append("checkpoint_fingerprint_sha256 is invalid")
    files = payload.get("fingerprinted_files")
    if not _fingerprint_file_list(files):
        failures.append("fingerprinted_files is invalid")
        return failures
    expected = fingerprint_sha256(
        base_head=str(payload["base_head"]),
        files=files,
    )
    if expected != payload.get("checkpoint_fingerprint_sha256"):
        failures.append("checkpoint fingerprint does not match declared files")
    if STATUS_FILE in {item["path"] for item in files}:
        failures.append("STATUS_FILE cannot be fingerprinted")
    failures.extend(_validate_changed_files_manifest(payload))
    return failures


def _validate_handoff_fields(
    payload: Mapping[str, Any],
    *,
    artifact_dir: Path | None,
) -> list[str]:
    artifacts = payload.get("artifacts")
    if not _artifact_list(artifacts):
        return ["artifacts is invalid"]
    failures: list[str] = []
    names = [item["filename"] for item in artifacts]
    if len(names) != len(set(names)):
        failures.append("handoff artifact filenames are not unique")
    types = {
        item["artifact_type"]
        for item in artifacts
        if isinstance(item, dict) and "artifact_type" in item
    }
    for public_type, wrapper_type in ARTIFACT_PAIRS:
        has_public = public_type in types
        has_wrapper = wrapper_type in types
        if has_public != has_wrapper:
            failures.append("handoff artifact public/wrapper pair is incomplete")
    for item in artifacts:
        cap = ARTIFACT_SIZE_CAPS[str(item["artifact_type"])]
        if int(item["size_bytes"]) > cap:
            failures.append("handoff artifact exceeds registered size cap")
    if (
        payload.get("autonomous_live_policy") == "BLOCKER"
        and payload.get("current_package") == "E2"
        and payload.get("implementation_status") == "COMPLETE"
        and (
            "autonomous_live_public" not in types
            or "autonomous_live_wrapper" not in types
        )
    ):
        failures.append("BLOCKER policy requires autonomous live public/wrapper pair")
    if artifact_dir is not None:
        failures.extend(
            _validate_artifact_files(
                artifacts,
                artifact_dir,
                resolved_commit=payload.get("resolved_completion_commit"),
            )
        )
    return failures


def _validate_strings_and_paths(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if _contains_absolute_path(payload):
        failures.append("absolute local path is not allowed")
    if _contains_raw_payload_marker(payload):
        failures.append("raw payload marker is not allowed")
    return failures


def _validate_ledger(
    payload: Mapping[str, Any],
    *,
    handoff: bool,
    previous_status: Mapping[str, Any] | None = None,
) -> list[str]:
    ledger = payload.get("package_ledger")
    if not isinstance(ledger, list) or not ledger:
        return ["package_ledger is empty"]
    failures: list[str] = []
    previous_digest: str | None = None
    policies: set[str] = set()
    for index, entry in enumerate(ledger):
        if not _ledger_entry(entry):
            failures.append("package_ledger entry is invalid")
            return failures
        if index == 0 and entry.get("previous_entry_sha256") is not None:
            failures.append("first ledger previous_entry_sha256 must be null")
        if index > 0 and entry.get("previous_entry_sha256") != previous_digest:
            failures.append("ledger hash-chain is broken")
        digest = ledger_entry_digest(entry)
        if digest != entry.get("entry_sha256"):
            failures.append("ledger entry_sha256 is incorrect")
        previous_digest = digest
        policies.add(str(entry.get("autonomous_live_policy")))
        if entry.get("package") not in PACKAGES:
            failures.append("ledger package is invalid")
    last = ledger[-1]
    if last.get("package") != payload.get("current_package"):
        failures.append("ledger package does not match current_package")
    if last.get("status") != payload.get("implementation_status"):
        failures.append("ledger status does not match implementation_status")
    if last.get("verdict") != payload.get("package_verdict"):
        failures.append("ledger verdict does not match package_verdict")
    if last.get("observed_head") != payload.get("observed_head"):
        failures.append("ledger observed_head does not match snapshot")
    if len(policies) != 1 or payload.get("autonomous_live_policy") not in policies:
        failures.append("autonomous_live_policy changed after initialization")
    if not handoff and last.get("package") == "E2":
        failures.append("tracked status cannot record E2")
    failures.extend(_validate_ledger_append_only(payload, previous_status))
    return failures


def _validate_package_transition(
    payload: Mapping[str, Any],
    *,
    handoff: bool,
    repo_root: Path | None = None,
) -> list[str]:
    failures: list[str] = []
    current = str(payload.get("current_package"))
    status = payload.get("implementation_status")
    verdict = payload.get("package_verdict")
    last_completed = payload.get("last_completed_package")
    next_allowed = payload.get("next_allowed_package")
    blockers = payload.get("blockers")
    if status == "COMPLETE" and verdict == "PASS":
        if not isinstance(blockers, list) or blockers:
            failures.append("COMPLETE+PASS requires empty blockers")
        if last_completed != current:
            failures.append("COMPLETE+PASS last_completed_package is incorrect")
        expected_next = next_package(current)
        if next_allowed != expected_next:
            failures.append("COMPLETE+PASS next_allowed_package is incorrect")
    else:
        if next_allowed != current:
            failures.append("unfinished package must keep next_allowed_package")
        if last_completed is not None:
            try:
                if PACKAGES.index(str(last_completed)) >= PACKAGES.index(current):
                    failures.append("last_completed_package is ahead of current")
            except ValueError:
                failures.append("package order is invalid")
    if current == "E2" and not handoff:
        failures.append("E2 is not allowed in the tracked status file")
    if current == "E2":
        completed = _completed_packages(payload.get("package_ledger"))
        if completed[: len(OFFLINE_PACKAGES)] != list(OFFLINE_PACKAGES):
            failures.append("E2 is forbidden before A-E1 COMPLETE+PASS")
    if status == "COMPLETE" and verdict == "NOT_RUN":
        failures.append("COMPLETE cannot have NOT_RUN verdict")
    if status == "IN_PROGRESS" and verdict == "PASS":
        failures.append("IN_PROGRESS cannot have PASS verdict")
    commit_state = payload.get("checkpoint_commit_state")
    if (
        not handoff
        and status == "COMPLETE"
        and verdict == "PASS"
        and commit_state != "READY_TO_COMMIT"
    ):
        failures.append("tracked COMPLETE+PASS requires READY_TO_COMMIT")
    if status == "IN_PROGRESS" and commit_state != "UNCOMMITTED":
        failures.append("IN_PROGRESS requires UNCOMMITTED checkpoint")
    completed = _completed_packages(payload.get("package_ledger"))
    try:
        current_index = PACKAGES.index(current)
    except ValueError:
        return failures
    if status == "COMPLETE" and verdict == "PASS":
        expected_completed = list(PACKAGES[: current_index + 1])
    else:
        expected_completed = list(PACKAGES[:current_index])
    if completed != expected_completed:
        failures.append("package order skipped")
    if repo_root is not None and not handoff:
        failures.extend(
            _validate_committed_predecessor_checkpoint(payload, repo_root)
        )
    return failures


PREDECESSOR_READY_CHECKPOINT_FAILURE = (
    "previous package lacks a committed READY_TO_COMMIT checkpoint"
)


def _committed_ready_checkpoint(
    snapshot: Mapping[str, Any] | None,
    *,
    package: str,
    repo_root: Path,
) -> bool:
    return not _committed_ready_checkpoint_failures(
        snapshot,
        package=package,
        repo_root=repo_root,
    )


def _committed_ready_checkpoint_failures(
    snapshot: Mapping[str, Any] | None,
    *,
    package: str,
    repo_root: Path,
) -> list[str]:
    if snapshot is None:
        return ["missing committed status checkpoint"]
    failures: list[str] = []
    if tuple(snapshot.keys()) != STATUS_KEYS:
        failures.append("committed checkpoint schema keys are invalid")
        return failures
    if snapshot.get("schema_version") != STATUS_SCHEMA_VERSION:
        failures.append("committed checkpoint schema_version is invalid")
    if snapshot.get("current_package") != package:
        failures.append("committed checkpoint package is invalid")
    if snapshot.get("implementation_status") != "COMPLETE":
        failures.append("committed checkpoint is not COMPLETE")
    if snapshot.get("package_verdict") != "PASS":
        failures.append("committed checkpoint verdict is not PASS")
    if snapshot.get("checkpoint_commit_state") != "READY_TO_COMMIT":
        failures.append("committed checkpoint is not READY_TO_COMMIT")
    parent = _first_parent(repo_root)
    if parent is None:
        failures.append("committed checkpoint has no causal parent")
    elif snapshot.get("observed_head") != parent:
        failures.append("committed checkpoint observed_head is not first parent")
    failures.extend(_validate_common_fields(snapshot, handoff=False))
    failures.extend(_validate_tracked_fields(snapshot))
    failures.extend(_validate_ledger(snapshot, handoff=False))
    failures.extend(
        _validate_package_transition(snapshot, handoff=False, repo_root=None)
    )
    failures.extend(_validate_lease_snapshot(snapshot, handoff=False))
    failures.extend(_validate_required_checks(snapshot, handoff=False))
    failures.extend(_validate_offline_cost(snapshot, handoff=False))
    if failures:
        return failures
    try:
        head = _git_output(repo_root, "rev-parse", "HEAD").strip()
        committed = observe_committed_diff(
            repo_root,
            base_head=str(snapshot["base_head"]),
            resolved_commit=head,
            package=package,
        )
    except (OSError, subprocess.CalledProcessError, StatusValidationError):
        return ["cannot observe committed checkpoint diff"]
    if committed["unexpected_paths"]:
        failures.append("committed checkpoint includes unexpected paths")
    declared = [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "state": item["state"],
        }
        for item in snapshot.get("fingerprinted_files", [])
        if isinstance(item, dict)
    ]
    if declared != committed["fingerprinted_files"]:
        failures.append("committed checkpoint fingerprinted_files mismatch")
    if committed["checkpoint_fingerprint_sha256"] != snapshot.get(
        "checkpoint_fingerprint_sha256"
    ):
        failures.append("committed checkpoint fingerprint mismatch")
    failures.extend(
        _validate_status_file_state_against_repository(
            snapshot,
            {
                "derived_resolved_completion_commit": head,
                "committed_file_states": committed["changed_file_states"],
            },
        )
    )
    ancestor = _git_output(
        repo_root,
        "merge-base",
        "--is-ancestor",
        str(snapshot["base_head"]),
        "HEAD",
        check=False,
    )
    if ancestor.returncode != 0:
        failures.append("committed checkpoint base_head is not an ancestor")
    return failures


def _validate_committed_predecessor_checkpoint(
    payload: Mapping[str, Any],
    repo_root: Path,
) -> list[str]:
    current = str(payload.get("current_package"))
    try:
        current_index = PACKAGES.index(current)
    except ValueError:
        return []
    if current_index == 0:
        return []
    fail = [PREDECESSOR_READY_CHECKPOINT_FAILURE]
    try:
        head_status = load_previous_status(repo_root)
    except StatusValidationError:
        return fail
    predecessor = PACKAGES[current_index - 1]
    head_package = head_status.get("current_package") if head_status else None
    expected = current if head_package == current else predecessor
    if _committed_ready_checkpoint(
        head_status, package=str(expected), repo_root=repo_root
    ):
        return []
    return fail


def _validate_lease_snapshot(
    payload: Mapping[str, Any],
    *,
    handoff: bool,
) -> list[str]:
    failures: list[str] = []
    lease = payload.get("lease_status")
    session_id = payload.get("active_session_id")
    status = payload.get("implementation_status")
    if lease == "RELEASED" and session_id is not None:
        failures.append("RELEASED lease requires null active_session_id")
    elif lease in {"ACTIVE", "STALE_CANDIDATE"} and not (
        isinstance(session_id, str) and UUID_RE.fullmatch(session_id)
    ):
        failures.append("ACTIVE lease requires one session UUID")
    if status == "COMPLETE" and lease != "RELEASED":
        failures.append("COMPLETE requires RELEASED lease")
    if status == "IN_PROGRESS":
        paused = payload.get("package_verdict") in {"HOLD", "BLOCKED"}
        if paused and lease == "RELEASED" and session_id is None:
            pass
        elif lease != "ACTIVE":
            failures.append("IN_PROGRESS requires ACTIVE lease")
    if handoff and lease == "ACTIVE" and payload.get("current_package") != "E2":
        failures.append("handoff ACTIVE lease is only valid for E2")
    return failures


def _validate_required_checks(
    payload: Mapping[str, Any],
    *,
    handoff: bool,
) -> list[str]:
    if payload.get("implementation_status") != "COMPLETE":
        return []
    if payload.get("package_verdict") != "PASS":
        return []
    package = str(payload.get("current_package"))
    required = PACKAGE_REQUIRED_CHECKS[package]
    passed_ids = [
        item["id"]
        for item in payload.get("checks_passed", [])
        if isinstance(item, dict)
    ]
    missing = [check_id for check_id in required if check_id not in passed_ids]
    if missing:
        return ["missing required check id"]
    if package == "E2" and not handoff:
        return ["E2 required checks cannot pass on tracked status"]
    return []


def _validate_offline_cost(payload: Mapping[str, Any], *, handoff: bool) -> list[str]:
    package = payload.get("current_package")
    if package == "E2" and handoff:
        return []
    failures: list[str] = []
    if payload.get("network_provider_calls") != 0:
        failures.append("offline package must record zero provider calls")
    if payload.get("provider_cost_status") not in {"zero", "not_run"}:
        failures.append("offline package must not record provider cost")
    return failures


def _validate_promotion(
    payload: Mapping[str, Any],
    *,
    handoff: bool,
    artifact_dir: Path | None = None,
    repo_root: Path | None = None,
    previous_status: Mapping[str, Any] | None = None,
) -> list[str]:
    promotion = payload.get("d11_promotion_status")
    if promotion != "PASS":
        return []
    if not handoff:
        return ["tracked status cannot set d11_promotion_status PASS"]
    if payload.get("current_package") != "E2":
        return ["promotion PASS requires E2 handoff"]
    if payload.get("implementation_status") != "COMPLETE":
        return ["promotion PASS requires E2 COMPLETE"]
    if payload.get("package_verdict") != "PASS":
        return ["promotion PASS requires E2 PASS"]
    if payload.get("checkpoint_commit_state") != "FROZEN_REVIEWED":
        return ["promotion PASS requires FROZEN_REVIEWED"]
    if payload.get("worktree_state") != "CLEAN":
        return ["promotion PASS requires CLEAN worktree"]
    if payload.get("lease_status") != "RELEASED":
        return ["promotion PASS requires RELEASED lease"]
    if not _commit(payload.get("resolved_completion_commit")):
        return ["promotion PASS requires resolved_completion_commit"]
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return ["promotion PASS requires handoff artifacts"]
    types = {item.get("artifact_type") for item in artifacts if isinstance(item, dict)}
    required_types = {
        "forced_live_public",
        "forced_live_wrapper",
        "clean_release",
        "promotion_report",
    }
    if not required_types.issubset(types):
        return ["promotion PASS is missing required evidence artifacts"]
    if payload.get("autonomous_live_policy") == "BLOCKER" and (
        "autonomous_live_public" not in types
        or "autonomous_live_wrapper" not in types
    ):
        return ["BLOCKER policy requires autonomous live public/wrapper pair"]
    if artifact_dir is None:
        return ["promotion PASS requires verified artifact files"]
    return _validate_promotion_provenance(
        payload,
        repo_root=repo_root,
        previous_status=previous_status,
    )


def _validate_against_repository(
    payload: Mapping[str, Any],
    repo_root: Path,
) -> list[str]:
    commit_state = payload.get("checkpoint_commit_state")
    try:
        observed = observe_checkpoint(repo_root, payload)
    except (OSError, subprocess.CalledProcessError, StatusValidationError):
        return ["cannot observe git worktree"]
    failures: list[str] = []
    origin = _git_output(repo_root, "rev-parse", "origin/main", check=False)
    if origin.returncode == 0:
        if origin.stdout.strip() != payload.get("observed_origin_main"):
            failures.append("observed_origin_main does not match origin/main")
    elif payload.get("observed_origin_main") != payload.get("observed_head"):
        failures.append(
            "observed_origin_main must match observed_head without origin/main"
        )
    dirty = bool(observed["changed_paths"])
    worktree_state = payload.get("worktree_state")
    if commit_state != "READY_TO_COMMIT":
        if dirty and worktree_state != "DIRTY_EXPECTED":
            failures.append("dirty worktree must be DIRTY_EXPECTED")
        if not dirty and worktree_state != "CLEAN":
            failures.append("clean worktree must be CLEAN")
    if commit_state == "READY_TO_COMMIT" and not dirty:
        parent = observed.get("first_parent")
        if not parent:
            failures.append("READY_TO_COMMIT clean checkpoint requires a parent commit")
        elif payload.get("observed_head") != parent:
            failures.append(
                "READY_TO_COMMIT observed_head must be first parent of HEAD"
            )
    elif observed["head"] != payload.get("observed_head"):
        failures.append("observed_head does not match git HEAD")
    allow_unexpected = (
        payload.get("implementation_status") == "IN_PROGRESS"
        and payload.get("package_verdict") in {"HOLD", "BLOCKED"}
    )
    if observed["unexpected_paths"] and not allow_unexpected:
        failures.append("unexpected path outside package write-set")
    if observed["checkpoint_fingerprint_sha256"] != payload.get(
        "checkpoint_fingerprint_sha256"
    ):
        failures.append("checkpoint fingerprint does not match repository")
    declared = [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "state": item["state"],
        }
        for item in payload.get("fingerprinted_files", [])
        if isinstance(item, dict)
    ]
    if declared != observed["fingerprinted_files"]:
        failures.append("fingerprinted_files do not match repository")
    failures.extend(_validate_status_file_state_against_repository(payload, observed))
    ancestor = _git_output(
        repo_root,
        "merge-base",
        "--is-ancestor",
        str(payload["base_head"]),
        "HEAD",
        check=False,
    )
    if ancestor.returncode != 0:
        failures.append("base_head is not an ancestor of HEAD")
    derived = observed.get("derived_resolved_completion_commit")
    if derived is not None:
        base_to_resolved = _git_output(
            repo_root,
            "merge-base",
            "--is-ancestor",
            str(payload["base_head"]),
            str(derived),
            check=False,
        )
        if base_to_resolved.returncode != 0:
            failures.append(
                "base_head is not an ancestor of derived resolved completion commit"
            )
    return failures


def _validate_ledger_append_only(
    payload: Mapping[str, Any],
    previous_status: Mapping[str, Any] | None,
) -> list[str]:
    if previous_status is None:
        return []
    failures: list[str] = []
    if previous_status.get("autonomous_live_policy") != payload.get(
        "autonomous_live_policy"
    ):
        failures.append("autonomous_live_policy changed from git checkpoint")
    previous_ledger = previous_status.get("package_ledger")
    current_ledger = payload.get("package_ledger")
    if not isinstance(previous_ledger, list) or not isinstance(current_ledger, list):
        failures.append("package_ledger is not append-only")
        return failures
    if len(current_ledger) < len(previous_ledger):
        failures.append("package_ledger entries were removed")
        return failures
    for index, previous_entry in enumerate(previous_ledger):
        if canonical_json(current_ledger[index]) != canonical_json(previous_entry):
            failures.append("package_ledger is not append-only")
            break
    return failures


def _fingerprint_worktree_files(
    repo_root: Path,
    *,
    base_head: str,
    package: str,
    changed_paths: Sequence[str],
) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for path in changed_paths:
        if path == STATUS_FILE or not _path_allowed(package, path):
            continue
        current = repo_root / path
        in_base = _path_in_ref(repo_root, base_head, path)
        if current.is_file():
            digest = hashlib.sha256(current.read_bytes()).hexdigest()
            state = "MODIFY" if in_base else "ADD"
        elif in_base:
            digest = DELETED_CONTENT_SHA256
            state = "DELETE"
        else:
            continue
        files.append({"path": path, "sha256": digest, "state": state})
    files.sort(key=lambda item: item["path"])
    return files


def _diff_status_to_state(code: str) -> str | None:
    marker = code[:1]
    if marker == "A":
        return "ADD"
    if marker == "M":
        return "MODIFY"
    if marker == "D":
        return "DELETE"
    return None


def _git_blob(repo_root: Path, ref: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise StatusValidationError("cannot read committed blob")
    return result.stdout


def _validate_changed_files_manifest(payload: Mapping[str, Any]) -> list[str]:
    files = payload.get("changed_files")
    fingerprinted = payload.get("fingerprinted_files")
    if not _changed_file_list(files) or not _fingerprint_file_list(fingerprinted):
        return []
    paths = [str(item["path"]) for item in files]
    if len(paths) != len(set(paths)):
        return ["changed_files paths are not unique"]
    status_entries = [item for item in files if item["path"] == STATUS_FILE]
    if len(status_entries) != 1:
        return ["changed_files must include STATUS_FILE"]
    declared = {(item["path"], item["state"]) for item in files}
    expected = {(item["path"], item["state"]) for item in fingerprinted}
    expected.add((STATUS_FILE, str(status_entries[0]["state"])))
    if declared != expected:
        return ["changed_files do not match fingerprinted_files"]
    return []


def _validate_status_file_state_against_repository(
    payload: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> list[str]:
    files = payload.get("changed_files")
    if not _changed_file_list(files):
        return []
    status_entries = [item for item in files if item["path"] == STATUS_FILE]
    if len(status_entries) != 1:
        return []
    expected = _observed_status_file_state(payload, observed)
    if expected is None:
        return ["STATUS_FILE state cannot be verified"]
    if status_entries[0]["state"] != expected:
        return ["STATUS_FILE state does not match repository"]
    return []


def _observed_status_file_state(
    payload: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> str | None:
    if (
        payload.get("checkpoint_commit_state") == "READY_TO_COMMIT"
        and observed.get("derived_resolved_completion_commit") is not None
    ):
        committed_states = observed.get("committed_file_states")
        if isinstance(committed_states, Mapping):
            state = committed_states.get(STATUS_FILE)
            return str(state) if state in FILE_STATES else None
        return None
    worktree_states = observed.get("changed_file_states")
    if isinstance(worktree_states, Mapping):
        state = worktree_states.get(STATUS_FILE)
        return str(state) if state in FILE_STATES else None
    return None


def _validate_promotion_provenance(
    payload: Mapping[str, Any],
    *,
    repo_root: Path | None,
    previous_status: Mapping[str, Any] | None,
) -> list[str]:
    if repo_root is None:
        return ["promotion PASS requires git repository"]
    if not isinstance(previous_status, dict):
        return ["promotion PASS requires committed E1 checkpoint"]
    if previous_status.get("current_package") != "E1":
        return ["promotion PASS requires committed E1 checkpoint"]
    if previous_status.get("implementation_status") != "COMPLETE":
        return ["promotion PASS requires E1 COMPLETE+PASS"]
    if previous_status.get("package_verdict") != "PASS":
        return ["promotion PASS requires E1 COMPLETE+PASS"]
    if previous_status.get("next_allowed_package") != "E2":
        return ["promotion PASS requires E1 next_allowed_package E2"]
    checkpoint_failures = _committed_ready_checkpoint_failures(
        previous_status,
        package="E1",
        repo_root=repo_root,
    )
    if checkpoint_failures:
        return ["promotion PASS requires valid committed E1 checkpoint"]
    try:
        head = _git_output(repo_root, "rev-parse", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError, StatusValidationError):
        return ["promotion PASS requires git HEAD"]
    if head != payload.get("resolved_completion_commit"):
        return ["resolved_completion_commit does not match git HEAD"]
    if payload.get("observed_head") != head:
        return ["observed_head does not match git HEAD"]
    origin = _git_output(repo_root, "rev-parse", "origin/main", check=False)
    if origin.returncode == 0:
        if payload.get("observed_origin_main") != origin.stdout.strip():
            return ["observed_origin_main does not match origin/main"]
    elif payload.get("observed_origin_main") != head:
        return ["observed_origin_main must match observed_head without origin/main"]
    if _git_status_paths(repo_root):
        return ["promotion PASS requires clean git worktree"]
    return []


def _validate_artifact_files(
    artifacts: Sequence[Mapping[str, Any]],
    artifact_dir: Path,
    *,
    resolved_commit: Any = None,
) -> list[str]:
    failures: list[str] = []
    bodies: list[tuple[Mapping[str, Any], bytes]] = []
    digest_by_type: dict[str, str] = {}
    payload_by_type: dict[str, Mapping[str, Any]] = {}
    for item in artifacts:
        filename = str(item.get("filename", ""))
        if not BASENAME_RE.fullmatch(filename):
            failures.append("handoff artifact file is missing")
            continue
        path = artifact_dir / filename
        if not path.is_file():
            failures.append("handoff artifact file is missing")
            continue
        data = path.read_bytes()
        if len(data) != item.get("size_bytes"):
            failures.append("handoff artifact size does not match file")
        digest = hashlib.sha256(data).hexdigest()
        if digest != item.get("sha256"):
            failures.append("handoff artifact digest does not match file")
        artifact_type = str(item["artifact_type"])
        digest_by_type[artifact_type] = digest
        cap = ARTIFACT_SIZE_CAPS.get(artifact_type, LIVE_EVIDENCE_MAX_BYTES)
        if len(data) > cap:
            failures.append("handoff artifact file exceeds registered cap")
        bodies.append((item, data))
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(decoded, Mapping):
            payload_by_type[artifact_type] = decoded
    for item, data in bodies:
        failures.extend(
            _validate_artifact_payload(
                str(item["artifact_type"]),
                data,
                resolved_commit=resolved_commit,
                digest_by_type=digest_by_type,
                payload_by_type=payload_by_type,
            )
        )
    return failures


def _validate_artifact_payload(
    artifact_type: str,
    data: bytes,
    *,
    resolved_commit: Any,
    digest_by_type: Mapping[str, str],
    payload_by_type: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ["handoff artifact is not JSON"]
    if not isinstance(payload, dict):
        return ["handoff artifact must be a JSON object"]
    failures: list[str] = []
    if artifact_type == "promotion_report":
        if payload.get("schema_version") != EVAL_REPORT_SCHEMA_VERSION:
            failures.append("promotion report schema_version is invalid")
        if payload.get("repository") != "agent-coach":
            failures.append("promotion report repository is invalid")
        if payload.get("commit") != resolved_commit:
            failures.append("promotion report commit does not match resolved commit")
        if payload.get("git_available") is not True:
            failures.append("promotion report git availability is invalid")
        if payload.get("worktree_dirty") is not False:
            failures.append("promotion report worktree state is invalid")
        if payload.get("gate_status") != "PASS":
            failures.append("promotion report gate_status is not PASS")
        if payload.get("promotion_status") != "PASS":
            failures.append("promotion report promotion_status is not PASS")
        if payload.get("threshold_failures") != []:
            failures.append("promotion report threshold_failures is not empty")
        if payload.get("promotion_blockers") != []:
            failures.append("promotion report promotion_blockers is not empty")
        live_evidence = payload.get("live_evidence")
        if not isinstance(live_evidence, Mapping):
            failures.append("promotion report live_evidence is invalid")
        elif live_evidence.get("status") != "available":
            failures.append("promotion report live_evidence is unavailable")
        clean_release = payload.get("clean_release_evidence")
        if not isinstance(clean_release, Mapping):
            failures.append("promotion report clean_release_evidence is invalid")
        elif clean_release.get("status") != "available":
            failures.append("promotion report clean_release_evidence is unavailable")
        else:
            failures.extend(
                _validate_promotion_report_evidence_links(
                    live_evidence=live_evidence,
                    clean_release=clean_release,
                    resolved_commit=resolved_commit,
                    digest_by_type=digest_by_type,
                    payload_by_type=payload_by_type,
                )
            )
    elif artifact_type in {"forced_live_public", "autonomous_live_public"}:
        public_failures = validate_live_eval_public_payload(
            payload,
            require_threshold=True,
        )
        failures.extend(f"live public {failure}" for failure in public_failures)
    elif artifact_type in {"forced_live_wrapper", "autonomous_live_wrapper"}:
        public_type = (
            "forced_live_public"
            if artifact_type == "forced_live_wrapper"
            else "autonomous_live_public"
        )
        if payload.get("schema_version") != LIVE_EVAL_WRAPPER_SCHEMA_VERSION:
            failures.append("live wrapper schema_version is invalid")
        if payload.get("provenance") != EXPECTED_LIVE_EVIDENCE_PROVENANCE:
            failures.append("live wrapper provenance is invalid")
        if payload.get("commit") != resolved_commit:
            failures.append("live wrapper commit does not match resolved commit")
        if payload.get("profile") != "live_provider":
            failures.append("live wrapper profile is invalid")
        if payload.get("provider_profile_opt_in") is not True:
            failures.append("live wrapper opt-in marker is invalid")
        if not _utc(payload.get("checked_at_utc")):
            failures.append("live wrapper checked_at_utc is invalid")
        case_count = payload.get("case_count")
        if (
            isinstance(case_count, bool)
            or not isinstance(case_count, int)
            or case_count < 5
        ):
            failures.append("live wrapper case_count is invalid")
        task_success_rate = _bounded_rate_value(payload.get("task_success_rate"))
        if task_success_rate is None:
            failures.append("live wrapper task_success_rate is invalid")
        artifacts = _public_artifact_records(payload.get("evidence_artifacts"))
        if artifacts is None:
            failures.append("live wrapper evidence_artifacts are invalid")
        public_digest = digest_by_type.get(public_type)
        if public_digest is not None and not _wrapper_references_public_digest(
            artifacts,
            public_digest,
        ):
            failures.append("live wrapper public digest does not match artifact file")
        public_payload = payload_by_type.get(public_type)
        if isinstance(public_payload, Mapping):
            if public_payload.get("case_count") != case_count:
                failures.append("live wrapper case_count does not match public")
            public_rate = _bounded_rate_value(public_payload.get("task_success_rate"))
            if (
                public_rate is None
                or task_success_rate is None
                or abs(public_rate - task_success_rate) > 0.000001
            ):
                failures.append("live wrapper task_success_rate does not match public")
    elif artifact_type == "clean_release":
        if payload.get("schema_version") != CLEAN_RELEASE_EVIDENCE_SCHEMA_VERSION:
            failures.append("clean release schema_version is invalid")
        if payload.get("provenance") != EXPECTED_CLEAN_RELEASE_EVIDENCE_PROVENANCE:
            failures.append("clean release provenance is invalid")
        if payload.get("commit") != resolved_commit:
            failures.append("clean release commit does not match resolved commit")
        if payload.get("worktree_dirty") is not False:
            failures.append("clean release worktree state is invalid")
        if not _utc(payload.get("checked_at_utc")):
            failures.append("clean release checked_at_utc is invalid")
        commands = payload.get("commands")
        if not isinstance(commands, Mapping):
            failures.append("clean release commands are invalid")
        else:
            for command_id, expected_command in EXPECTED_CLEAN_RELEASE_COMMANDS.items():
                command = commands.get(command_id)
                if not isinstance(command, Mapping):
                    failures.append("clean release command is missing")
                    continue
                if command.get("status") != "PASS" or command.get("exit_code") != 0:
                    failures.append("clean release command did not pass")
                if command.get("command") != expected_command:
                    failures.append("clean release command text is invalid")
                if not SHA256_RE.fullmatch(str(command.get("stdout_sha256") or "")):
                    failures.append("clean release command stdout_sha256 is invalid")
    return failures


def _validate_promotion_report_evidence_links(
    *,
    live_evidence: Any,
    clean_release: Mapping[str, Any],
    resolved_commit: Any,
    digest_by_type: Mapping[str, str],
    payload_by_type: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    failures: list[str] = []
    forced_public = payload_by_type.get("forced_live_public")
    forced_wrapper = payload_by_type.get("forced_live_wrapper")
    clean_artifact = payload_by_type.get("clean_release")
    if not isinstance(live_evidence, Mapping):
        return ["promotion report live_evidence is invalid"]
    if live_evidence.get("commit") != resolved_commit:
        failures.append("promotion report live_evidence commit mismatch")
    if clean_release.get("commit") != resolved_commit:
        failures.append("promotion report clean_release commit mismatch")
    wrapper_rate = None
    if isinstance(forced_wrapper, Mapping):
        wrapper_rate = _bounded_rate_value(forced_wrapper.get("task_success_rate"))
        if live_evidence.get("case_count") != forced_wrapper.get("case_count"):
            failures.append("promotion report live_evidence case_count mismatch")
        live_rate = _bounded_rate_value(live_evidence.get("task_success_rate"))
        if (
            live_rate is None
            or wrapper_rate is None
            or abs(live_rate - wrapper_rate) > 0.000001
        ):
            failures.append("promotion report live_evidence task_success_rate mismatch")
    if isinstance(forced_public, Mapping):
        public_rate = _bounded_rate_value(forced_public.get("task_success_rate"))
        if wrapper_rate is not None and (
            public_rate is None or abs(public_rate - wrapper_rate) > 0.000001
        ):
            failures.append("promotion report live_evidence public rate mismatch")
    artifacts = _public_artifact_records(live_evidence.get("evidence_artifacts"))
    public_digest = digest_by_type.get("forced_live_public")
    if public_digest is not None and not _wrapper_references_public_digest(
        artifacts,
        public_digest,
    ):
        failures.append("promotion report live_evidence artifact digest mismatch")
    if isinstance(clean_artifact, Mapping):
        if clean_release.get("checked_at_utc") != clean_artifact.get("checked_at_utc"):
            failures.append("promotion report clean_release timestamp mismatch")
        if clean_release.get("commands") != _project_clean_release_commands(
            clean_artifact.get("commands")
        ):
            failures.append("promotion report clean_release commands mismatch")
    return failures


def _bounded_rate_value(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    rate = float(value)
    if 0.0 <= rate <= 1.0:
        return rate
    return None


def _public_artifact_records(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list) or not value:
        return None
    records: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        label = item.get("label")
        digest = item.get("sha256")
        if not _public_artifact_label(label):
            return None
        if not (isinstance(digest, str) and SHA256_RE.fullmatch(digest)):
            return None
        records.append({"label": label, "sha256": digest})
    return records


def _public_artifact_label(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value == "docs/evidence/live-eval-public.json":
        return True
    return (
        "/" not in value
        and "\\" not in value
        and value.endswith(".json")
        and BASENAME_RE.fullmatch(value) is not None
    )


def _project_clean_release_commands(value: Any) -> dict[str, dict[str, object]] | None:
    if not isinstance(value, Mapping):
        return None
    projected: dict[str, dict[str, object]] = {}
    for command_id, expected_command in EXPECTED_CLEAN_RELEASE_COMMANDS.items():
        command = value.get(command_id)
        if not isinstance(command, Mapping):
            return None
        stdout_sha256 = command.get("stdout_sha256")
        if not (isinstance(stdout_sha256, str) and SHA256_RE.fullmatch(stdout_sha256)):
            return None
        projected[command_id] = {
            "command": expected_command,
            "exit_code": 0,
            "status": "PASS",
            "stdout_sha256": stdout_sha256,
        }
    return projected


def _wrapper_references_public_digest(artifacts: Any, public_digest: str) -> bool:
    if not isinstance(artifacts, list):
        return False
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        if _public_artifact_label(item.get("label")) and item.get(
            "sha256"
        ) == public_digest:
            return True
    return False


def _completed_packages(ledger: Any) -> list[str]:
    latest: dict[str, Mapping[str, Any]] = {}
    order: list[str] = []
    if not isinstance(ledger, list):
        return []
    for entry in ledger:
        if not isinstance(entry, dict):
            continue
        package = entry.get("package")
        if package not in PACKAGES:
            continue
        if package not in latest:
            order.append(str(package))
        latest[str(package)] = entry
    completed: list[str] = []
    for package in order:
        entry = latest[package]
        if entry.get("status") == "COMPLETE" and entry.get("verdict") == "PASS":
            completed.append(package)
    return completed


def _path_allowed(package: str, path: str) -> bool:
    if path in PACKAGE_WRITE_SETS.get(package, frozenset()):
        return True
    prefixes = PACKAGE_WRITE_PREFIXES.get(package, ())
    return any(path.startswith(prefix) for prefix in prefixes)


def _changed_file_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict) or tuple(item.keys()) != CHANGED_FILE_KEYS:
            return False
        if not _repo_path(item.get("path")):
            return False
        if item.get("state") not in FILE_STATES:
            return False
        purpose = item.get("purpose")
        max_purpose = MAX_STRING_CHARS["purpose"]
        if not isinstance(purpose, str) or not purpose or len(purpose) > max_purpose:
            return False
    return True


def _fingerprint_file_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    paths: list[str] = []
    for item in value:
        if not isinstance(item, dict) or tuple(item.keys()) != FINGERPRINT_FILE_KEYS:
            return False
        if not _repo_path(item.get("path")):
            return False
        if item.get("state") not in FILE_STATES:
            return False
        digest = item.get("sha256")
        if not (isinstance(digest, str) and SHA256_RE.fullmatch(digest)):
            return False
        paths.append(str(item["path"]))
    return paths == sorted(paths) and len(paths) == len(set(paths))


def _check_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or tuple(item.keys()) != CHECK_KEYS:
            return False
        check_id = item.get("id")
        if not isinstance(check_id, str) or not check_id or check_id in seen:
            return False
        if len(check_id) > MAX_STRING_CHARS["id"]:
            return False
        seen.add(check_id)
        command = item.get("command")
        platform = item.get("platform")
        if not isinstance(command, str) or not command:
            return False
        if len(command) > MAX_STRING_CHARS["command"]:
            return False
        if not isinstance(platform, str) or not platform:
            return False
        if len(platform) > MAX_STRING_CHARS["platform"]:
            return False
        if item.get("result") not in CHECK_RESULTS:
            return False
    return True


def _ledger_entry(value: Any) -> bool:
    if not isinstance(value, dict) or tuple(value.keys()) != LEDGER_KEYS:
        return False
    if value.get("package") not in PACKAGES:
        return False
    if value.get("status") not in IMPLEMENTATION_STATUSES:
        return False
    if value.get("verdict") not in PACKAGE_VERDICTS:
        return False
    if not _commit(value.get("observed_head")):
        return False
    if not _utc(value.get("completed_at_utc")):
        return False
    summary = value.get("evidence_summary")
    if not isinstance(summary, str) or not summary:
        return False
    if len(summary) > MAX_STRING_CHARS["evidence_summary"]:
        return False
    if value.get("autonomous_live_policy") not in POLICIES:
        return False
    previous = value.get("previous_entry_sha256")
    if previous is not None and not (
        isinstance(previous, str) and SHA256_RE.fullmatch(previous)
    ):
        return False
    digest = value.get("entry_sha256")
    return isinstance(digest, str) and SHA256_RE.fullmatch(digest)


def _artifact_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict) or tuple(item.keys()) != ARTIFACT_KEYS:
            return False
        if item.get("artifact_type") not in HANDOFF_ARTIFACT_TYPES:
            return False
        filename = item.get("filename")
        if not isinstance(filename, str) or not BASENAME_RE.fullmatch(filename):
            return False
        size = item.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            return False
        if size > PROMOTION_REPORT_MAX_BYTES:
            return False
        digest = item.get("sha256")
        if not (isinstance(digest, str) and SHA256_RE.fullmatch(digest)):
            return False
    return True


def _string_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 400:
            return False
    return True


def _utc(value: Any) -> bool:
    return isinstance(value, str) and bool(UTC_RE.fullmatch(value))


def _commit(value: Any) -> bool:
    return isinstance(value, str) and bool(COMMIT_RE.fullmatch(value))


def _repo_path(value: Any) -> bool:
    return isinstance(value, str) and bool(REPO_PATH_RE.fullmatch(value))


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _contains_absolute_path(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in ABSOLUTE_PATH_RE)
    if isinstance(value, list):
        return any(_contains_absolute_path(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_absolute_path(item) for item in value.values())
    return False


def _contains_raw_payload_marker(value: Any) -> bool:
    markers = ("BEGIN PRIVATE KEY", "chain-of-thought", "raw provider")
    if isinstance(value, str):
        folded = value.casefold()
        return any(marker.casefold() in folded for marker in markers)
    if isinstance(value, list):
        return any(_contains_raw_payload_marker(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_raw_payload_marker(item) for item in value.values())
    return False


def _first_parent(repo_root: Path) -> str | None:
    result = _git_output(repo_root, "rev-parse", "HEAD^", check=False)
    if result.returncode != 0:
        return None
    parent = result.stdout.strip()
    if not _commit(parent):
        return None
    return parent


def _git_status_paths(repo_root: Path) -> tuple[str, ...]:
    output = _git_output(repo_root, "status", "--short", "--untracked-files=all")
    paths: list[str] = []
    for _state, path in _parse_git_status_short(output):
        if path:
            paths.append(path)
    return tuple(dict.fromkeys(paths))


def _git_status_file_states(repo_root: Path) -> dict[str, str]:
    output = _git_output(repo_root, "status", "--short", "--untracked-files=all")
    states: dict[str, str] = {}
    for state, path in _parse_git_status_short(output):
        if path and state is not None:
            states[path] = state
    return states


def _parse_git_status_short(output: str) -> list[tuple[str | None, str]]:
    entries: list[tuple[str | None, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        code = line[:2]
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        path = raw.strip().strip('"').replace("\\", "/")
        entries.append((_short_status_to_state(code), path))
    return entries


def _short_status_to_state(code: str) -> str | None:
    if "?" in code:
        return "ADD"
    if "D" in code:
        return "DELETE"
    if "A" in code:
        return "ADD"
    if "M" in code:
        return "MODIFY"
    return None


def _path_in_ref(repo_root: Path, ref: str, path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _git_output(
    repo_root: Path,
    *args: str,
    check: bool = True,
) -> Any:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise StatusValidationError("git command failed")
    if check:
        return result.stdout
    return result


def _bounded_diagnostic(value: str) -> str:
    compact = " ".join(value.split())
    if len(compact) <= MAX_DIAGNOSTIC_CHARS:
        return compact
    return compact[: MAX_DIAGNOSTIC_CHARS - 3] + "..."


def new_session_id() -> str:
    return str(uuid.uuid4())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
