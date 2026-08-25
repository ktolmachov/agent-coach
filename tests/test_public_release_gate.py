from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

from scripts import check_public_release as gate
from scripts import run_live_eval

from agent_coach.api import create_app
from agent_coach.eval.live_evidence import (
    LIVE_EXECUTION_BACKEND,
    UNEXPECTED_PUBLIC_FIELD_FAILURE,
    UNSAFE_PUBLIC_VALUE_FAILURE,
    live_eval_case_registry_hash,
    live_eval_contract_hash,
    live_eval_corpus_hash,
)


def test_public_release_gate_passes() -> None:
    assert gate.main() == 0


def test_public_release_gate_has_help_and_release_mode(
    capsys,
) -> None:
    try:
        gate.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    captured = capsys.readouterr()
    assert "--release" in captured.out


def test_strict_release_mode_rejects_dirty_tree_without_requiring_live_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    _write_required_files(tmp_path)
    (tmp_path / "docs" / "prompts").mkdir(exist_ok=True)
    (tmp_path / "docs" / "prompts" / "architecture_review_prompt.md").write_text(
        "# Architecture Review Prompt\n",
        encoding="utf-8",
    )

    def fake_git(_repo_root: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return "clean-head\n"
        if args == ("status", "--short"):
            return " M README.md\n"
        if args == ("ls-files", "--cached", "--others", "--exclude-standard"):
            return ""
        return ""

    monkeypatch.setattr(gate, "_git_output", fake_git)

    failures = gate.build_failures(tmp_path, release_mode=True)

    assert "strict release mode requires a clean worktree" in failures
    assert (
        "strict release artifact is missing: docs/evidence/live-eval-public.json"
        not in failures
    )


def test_live_eval_public_evidence_schema_is_validated() -> None:
    payload = _valid_live_public_payload()
    head = str(payload["evaluated_commit"])

    assert (
        gate._validate_evidence_payload(
            Path("docs/evidence/live-eval-public.json"),
            payload,
            head,
        )
        == []
    )

    payload["contains_scripted_responses"] = True
    assert (
        "scripted responses are not live evidence: "
        "docs/evidence/live-eval-public.json"
    ) in gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        payload,
        head,
    )

    payload = _valid_live_public_payload()
    payload["results"] = [{}, {}, {}, {}, {}]
    payload["task_success_rate"] = 0.8
    failures = gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        payload,
        head,
    )

    assert any(
        "live eval results do not match registered case ids" in item
        for item in failures
    )
    assert any(
        "live eval task_success_rate does not match per-case results" in item
        for item in failures
    )


def test_live_eval_public_case_contract_freezes_review_fields() -> None:
    payload = _valid_live_public_payload()
    payload["cases"][0]["question"] = "A different experiment question?"
    payload["cases"][0]["security_assertions"] = []
    payload["cases"][0]["success_rule"] = "always pass"

    failures = gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        payload,
        str(payload["evaluated_commit"]),
    )

    assert any("live eval case question mismatch" in item for item in failures)
    assert any("live eval case contract mismatch" in item for item in failures)
    assert any("live eval case success rule mismatch" in item for item in failures)

    unchanged = deepcopy(_valid_live_public_payload())
    assert gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        unchanged,
        str(unchanged["evaluated_commit"]),
    ) == []


def test_public_release_gate_rejects_oversized_live_eval_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    path = Path("docs/evidence/live-eval-public.json")
    artifact = tmp_path / path
    artifact.parent.mkdir(parents=True)
    payload = _valid_live_public_payload()
    payload["padding"] = "x" * 80_000
    artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate,
        "_git_output",
        lambda *_args: "head" if _args[1:] == ("rev-parse", "HEAD") else "",
    )

    failures = gate._check_evidence_artifacts(tmp_path, [path])

    assert failures == [
        "malformed release evidence docs/evidence/live-eval-public.json: "
        "live eval public evidence exceeds 64000 bytes"
    ]


def test_publishable_scan_rejects_generic_secrets_and_private_paths(tmp_path) -> None:
    paths = [
        Path("docs/probe.md"),
        Path("tests/probe.py"),
        Path("docs/secret.txt"),
    ]
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    windows_path = "C:" + "\\".join(("", "Users", "Alice", "secret.txt"))
    posix_path = "/".join(("", "home", "alice", "secret.txt"))
    token_value = "-".join(("realistic", "token", "value", "1234567890"))
    aws_secret = "AWS_SECRET_ACCESS_KEY=" + "ABCDEFGHIJKLMNOPQRST" + "1234567890"
    (tmp_path / paths[0]).write_text(
        f"{windows_path}\n{posix_path}\n",
        encoding="utf-8",
    )
    (tmp_path / paths[1]).write_text(
        f"token = '{token_value}'\n",
        encoding="utf-8",
    )
    (tmp_path / paths[2]).write_text(
        f"{aws_secret}\n",
        encoding="utf-8",
    )

    failures = gate._check_publishable_text(tmp_path, paths)

    assert any(
        "private local path marker in docs/probe.md" in item for item in failures
    )
    assert any("secret-like token in tests/probe.py" in item for item in failures)
    assert any("secret-like token in docs/secret.txt" in item for item in failures)


def test_private_path_allowlist_does_not_exclude_whole_test_files(tmp_path) -> None:
    path = Path("tests/test_core.py")
    (tmp_path / "tests").mkdir()
    allowed = "D:" + "\\".join(("", "Projects", "hometutor", "secret.md"))
    real = "C:" + "\\".join(("", "Users", "Alice", "real-private.txt"))
    (tmp_path / path).write_text(
        f"ALLOWED_FIXTURE = {allowed!r}\nREAL_PRIVATE = {real!r}\n",
        encoding="utf-8",
    )

    failures = gate._check_publishable_text(tmp_path, [path])

    assert failures == ["private local path marker in tests/test_core.py"]


def test_markdown_scan_rejects_custom_hometutor_checkout_paths(tmp_path) -> None:
    path = Path("docs/custom.md")
    (tmp_path / "docs").mkdir()
    custom_path = "/" + "/".join(("custom", "hometutor", "private.md"))
    (tmp_path / path).write_text(f"{custom_path}\n", encoding="utf-8")

    failures = gate._check_publishable_text(tmp_path, [path])

    assert failures == ["private local path marker in docs/custom.md"]


def test_secret_allowlist_requires_exact_fixture_matches(tmp_path) -> None:
    path = Path("tests/test_mock_adapters.py")
    (tmp_path / "tests").mkdir()
    fake_secret = "api_key=" + "DEMOSECRET_REAL_CREDENTIAL_123456789"
    fake_token = "token=" + "prefix-demo-token-realcredential123456789"
    (tmp_path / path).write_text(f"{fake_secret}\n{fake_token}\n", encoding="utf-8")

    failures = gate._check_publishable_text(tmp_path, [path])

    assert failures == ["secret-like token in tests/test_mock_adapters.py"]


def test_release_surface_scans_unknown_suffix_and_suffixless_files(tmp_path) -> None:
    paths = [
        Path("NOTICE"),
        Path("scripts/leak.ps1"),
    ]
    (tmp_path / "scripts").mkdir()
    ghp_token = "ghp_" + ("A" * 30)
    private_path = "C:" + "\\".join(("", "Users", "Alice", "real-private.txt"))
    (tmp_path / "NOTICE").write_text(f"{ghp_token}\n", encoding="utf-8")
    (tmp_path / "scripts" / "leak.ps1").write_text(
        f"Write-Output {private_path!r}\n",
        encoding="utf-8",
    )

    failures = gate._check_publishable_text(tmp_path, paths)

    assert failures == [
        "secret-like token in NOTICE",
        "private local path marker in scripts/leak.ps1",
    ]


def test_sensitive_container_files_are_blocked() -> None:
    paths = [
        Path(".env"),
        Path(".env.local"),
        Path("leaked.pem"),
        Path("certs/private.key"),
        Path("certs/bundle.p12"),
        Path(".env.example"),
    ]

    failures = gate._check_sensitive_containers(paths)

    assert failures == [
        "sensitive credential container is not release-safe: .env",
        "sensitive credential container is not release-safe: .env.local",
        "sensitive credential container is not release-safe: leaked.pem",
        "sensitive credential container is not release-safe: certs/private.key",
        "sensitive credential container is not release-safe: certs/bundle.p12",
    ]


def test_secret_scan_rejects_pem_github_and_openai_tokens(tmp_path) -> None:
    path = Path("docs/secrets.md")
    (tmp_path / "docs").mkdir()
    pem = "-----BEGIN " + "PRIVATE KEY-----"
    github_classic = "ghp_" + ("B" * 30)
    github_fine_grained = "github_pat_" + ("C" * 40)
    openai_project = "sk-" + "proj-" + ("D" * 30)
    (tmp_path / path).write_text(
        "\n".join((pem, github_classic, github_fine_grained, openai_project)),
        encoding="utf-8",
    )

    failures = gate._check_publishable_text(tmp_path, [path])

    assert failures == ["secret-like token in docs/secrets.md"]


def test_secret_scan_rejects_encrypted_and_pgp_private_keys_in_markdown(
    tmp_path,
) -> None:
    path = Path("docs/probe.md")
    (tmp_path / "docs").mkdir()
    encrypted_pem = "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"
    pgp_block = "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"
    (tmp_path / path).write_text(
        f"{encrypted_pem}\n{pgp_block}\n",
        encoding="utf-8",
    )

    failures = gate._check_publishable_text(tmp_path, [path])

    assert failures == ["secret-like token in docs/probe.md"]


def test_production_claims_are_rejected_in_all_markdown(tmp_path) -> None:
    paths = [Path("README.md"), Path("docs/claims.md")]
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(
        "standalone deterministic diploma demo\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "claims.md").write_text(
        "This is production-ready.\n",
        encoding="utf-8",
    )

    failures = gate._check_readme_claims(tmp_path, paths)

    assert failures == [
        "production readiness claim in docs/claims.md: production-ready"
    ]


def test_security_reporting_requires_concrete_fallback_recipient(tmp_path) -> None:
    _write_required_files(tmp_path)
    (tmp_path / "SECURITY.md").write_text(
        "Use GitHub Private Vulnerability Reporting when enabled.\n",
        encoding="utf-8",
    )

    failures = gate._check_required_files(tmp_path)

    assert "concrete fallback private security recipient is missing" in failures


def test_release_evidence_rejects_dirty_or_stale_payload() -> None:
    payload = {
        "schema_version": gate.EVIDENCE_SCHEMA_VERSION,
        "commit": "previous",
        "worktree_dirty": True,
        "adapter_profile": "mock",
        "result": {"success": True},
    }

    failures = gate._validate_evidence_payload(
        Path("docs/evidence/diploma_demo.json"),
        payload,
        "current",
    )

    assert (
        "release evidence commit does not match HEAD: "
        "docs/evidence/diploma_demo.json"
    ) in failures
    assert (
        "release evidence was generated from a dirty worktree: "
        "docs/evidence/diploma_demo.json"
    ) in failures


def test_release_gate_rejects_invalid_evidence_file(tmp_path) -> None:
    _write_required_files(tmp_path)
    _init_git(tmp_path)
    evidence = tmp_path / "docs" / "evidence" / "diploma_demo.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        json.dumps(
            {
                "schema_version": gate.EVIDENCE_SCHEMA_VERSION,
                "commit": "previous",
                "worktree_dirty": True,
                "adapter_profile": "mock",
                "result": {"success": True},
            }
        ),
        encoding="utf-8",
    )

    failures = gate.build_failures(tmp_path)

    assert any(
        "release evidence commit does not match HEAD" in item for item in failures
    )
    assert any(
        "release evidence was generated from a dirty worktree" in item
        for item in failures
    )


def test_d11_eval_artifact_check_reports_missing_tool_sop(tmp_path) -> None:
    _write_required_files(tmp_path)
    (tmp_path / "docs" / "tool_sop.md").unlink()

    failures = gate._check_d11_eval_artifacts(tmp_path)

    assert "docs/tool_sop.md is missing or unreadable" in failures


def test_public_release_gate_tracks_eval_v2_case_count_docs() -> None:
    eval_gate = Path("docs/eval_gate.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    implementation_plan = Path("docs/implementation_plan.md").read_text(
        encoding="utf-8"
    )

    assert "It contains 47 public synthetic" in eval_gate
    assert "exactly 47 public synthetic cases" in readme
    assert "exactly 47 registered frozen cases" in implementation_plan


def test_final_release_checklist_documents_full_promotion_command() -> None:
    checklist = Path("docs/release_checklist.md").read_text(encoding="utf-8")
    command = _promotion_command_from_checklist(checklist)

    assert command["script"] == "scripts/run_eval_gate.py"
    assert command["--live-evidence"] == "../agent-coach-live-wrapper.json"
    assert (
        command["--clean-release-evidence"]
        == "../agent-coach-clean-release-evidence.json"
    )
    assert command["--require-promotion"] is True
    assert command["--output"] == "../agent-coach-d11-promotion-report.json"
    for flag in ("--live-evidence", "--clean-release-evidence", "--output"):
        assert command[flag].startswith("../")


def test_ci_runs_offline_eval_without_promotion_flags() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python -m compileall src scripts" in workflow
    assert "name: Check strict public release hygiene" in workflow
    assert "python scripts/check_public_release.py --release" in workflow
    assert "run: python scripts/run_eval_gate.py" in workflow
    eval_line = next(
        line for line in workflow.splitlines() if "scripts/run_eval_gate.py" in line
    )
    assert "--live-evidence" not in eval_line
    assert "--require-promotion" not in eval_line


def _write_required_files(root: Path) -> None:
    for directory in ("docs", "contracts"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    (root / "NOTICE").write_text("Apache-2.0\n", encoding="utf-8")
    (root / "README.md").write_text(
        "standalone deterministic diploma demo\n",
        encoding="utf-8",
    )
    (root / "SECURITY.md").write_text(
        "Private Vulnerability Reporting\n"
        "Fallback private security recipient: private review recipient.\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("license = { text = \"Apache-2.0\" }\n")
    (root / "docs" / "review_kit.md").write_text("# Review\n", encoding="utf-8")
    (root / "docs" / "release_checklist.md").write_text(
        "# Release\n",
        encoding="utf-8",
    )
    (root / "docs" / "dependency_notices.md").write_text(
        "# Dependencies\n",
        encoding="utf-8",
    )
    eval_suite_path = "/".join(
        ("src", "agent_coach", "data", "diploma_eval_cases.json")
    )
    (root / "docs" / "eval_gate.md").write_text(
        f"`{eval_suite_path}`. It contains 47 public synthetic cases.\n",
        encoding="utf-8",
    )
    (root / "docs" / "tool_sop.md").write_text(
        gate.build_tool_sop_markdown(),
        encoding="utf-8",
    )
    (root / "docs" / "prompts").mkdir(exist_ok=True)
    (root / "docs" / "prompts" / "architecture_review_prompt.md").write_text(
        "# Architecture Review Prompt\n",
        encoding="utf-8",
    )
    (root / "docs" / "openapi.json").write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "contracts" / "export_manifest.json").write_text("{}\n", encoding="utf-8")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "run_live_eval.py").write_text("# live eval\n")


def _promotion_command_from_checklist(text: str) -> dict[str, object]:
    prefix = "python scripts/run_eval_gate.py --live-evidence "
    line = next(line for line in text.splitlines() if line.startswith(prefix))
    parts = line.split()
    parsed: dict[str, object] = {"script": parts[1]}
    index = 2
    while index < len(parts):
        flag = parts[index]
        if flag == "--require-promotion":
            parsed[flag] = True
            index += 1
            continue
        parsed[flag] = parts[index + 1]
        index += 2
    return parsed


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "review@example.test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Review"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_historical_live_example_is_not_current_and_skips_head_match() -> None:
    payload = _historical_live_public_payload()
    path = Path("docs/evidence/historical/live-eval-public.json")

    assert gate._validate_evidence_payload(path, payload, "other-head") == []


def test_historical_payload_on_current_path_is_rejected() -> None:
    payload = _historical_live_public_payload()
    failures = gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        payload,
        "other-head",
    )
    assert any(
        "path and classification mismatch" in item for item in failures
    )


def test_current_payload_on_historical_path_is_rejected() -> None:
    payload = _valid_live_public_payload()
    failures = gate._validate_evidence_payload(
        Path("docs/evidence/historical/live-eval-public.json"),
        payload,
        str(payload["evaluated_commit"]),
    )
    assert any(
        "path and classification mismatch" in item for item in failures
    )


def test_current_live_evidence_must_match_release_head() -> None:
    payload = _valid_live_public_payload()
    failures = gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        payload,
        "ffffffffffffffffffffffffffffffffffffffff",
    )
    assert any("does not match expected commit" in item for item in failures)


def test_current_live_evidence_rejects_unexpected_fields() -> None:
    payload = _valid_live_public_payload()
    payload["raw_provider_payload"] = {"note": "not-in-schema"}
    failures = gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        payload,
        str(payload["evaluated_commit"]),
    )
    assert any(UNEXPECTED_PUBLIC_FIELD_FAILURE in item for item in failures)

    nested = _valid_live_public_payload()
    nested["results"][0]["raw_provider_payload"] = {"note": "not-in-schema"}
    nested_failures = gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        nested,
        str(nested["evaluated_commit"]),
    )
    assert any(UNEXPECTED_PUBLIC_FIELD_FAILURE in item for item in nested_failures)


def test_current_live_evidence_rejects_secret_in_allowed_backend() -> None:
    payload = _valid_live_public_payload()
    payload["model_projection"]["planner"]["backend"] = "sk-proj-EXAMPLE"
    failures = gate._validate_evidence_payload(
        Path("docs/evidence/live-eval-public.json"),
        payload,
        str(payload["evaluated_commit"]),
    )
    assert any(UNSAFE_PUBLIC_VALUE_FAILURE in item for item in failures)


def _valid_live_public_payload() -> dict[str, object]:
    payload = run_live_eval.run_live_eval(scripted=True)
    payload["mode"] = "live_provider"
    payload["contains_scripted_responses"] = False
    payload["provider_profile_opt_in"] = True
    payload["execution_backend"] = LIVE_EXECUTION_BACKEND
    payload["evaluated_commit"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    payload["clean_worktree"] = True
    payload["contract_hash"] = live_eval_contract_hash()
    payload["corpus_hash"] = live_eval_corpus_hash()
    payload["case_registry_hash"] = live_eval_case_registry_hash()
    payload["model_projection"] = {
        "planner": {
            "role": "planner",
            "model_id": "gpt-4.1-mini",
            "backend": "openai_responses",
        },
        "synthesizer": {
            "role": "synthesizer",
            "model_id": "gpt-4.1",
            "backend": "openai_responses",
        },
    }
    return payload


def _historical_live_public_payload() -> dict[str, object]:
    payload = run_live_eval.run_live_eval(scripted=True)
    payload["mode"] = "live_provider"
    payload["contains_scripted_responses"] = False
    payload["provider_profile_opt_in"] = True
    payload["historical_evaluated_commit"] = (
        "829df29e58f6dd48fb09ee1400dec3c4115ad6b9"
    )
    payload["provenance"] = {
        "classification": "historical_example",
        "contains_credentials": False,
        "contains_learner_data": False,
        "contains_hometutor_runtime_dependency": False,
        "contains_raw_provider_payloads": False,
    }
    return payload
