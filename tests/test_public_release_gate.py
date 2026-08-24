from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import check_public_release as gate

from agent_coach.api import create_app


def test_public_release_gate_passes() -> None:
    assert gate.main() == 0


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
        "private local path marker in docs\\probe.md" in item for item in failures
    )
    assert any("secret-like token in tests\\probe.py" in item for item in failures)
    assert any("secret-like token in docs\\secret.txt" in item for item in failures)


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

    assert failures == ["private local path marker in tests\\test_core.py"]


def test_markdown_scan_rejects_custom_hometutor_checkout_paths(tmp_path) -> None:
    path = Path("docs/custom.md")
    (tmp_path / "docs").mkdir()
    custom_path = "/" + "/".join(("custom", "hometutor", "private.md"))
    (tmp_path / path).write_text(f"{custom_path}\n", encoding="utf-8")

    failures = gate._check_publishable_text(tmp_path, [path])

    assert failures == ["private local path marker in docs\\custom.md"]


def test_secret_allowlist_requires_exact_fixture_matches(tmp_path) -> None:
    path = Path("tests/test_mock_adapters.py")
    (tmp_path / "tests").mkdir()
    fake_secret = "api_key=" + "DEMOSECRET_REAL_CREDENTIAL_123456789"
    fake_token = "token=" + "prefix-demo-token-realcredential123456789"
    (tmp_path / path).write_text(f"{fake_secret}\n{fake_token}\n", encoding="utf-8")

    failures = gate._check_publishable_text(tmp_path, [path])

    assert failures == ["secret-like token in tests\\test_mock_adapters.py"]


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
        "private local path marker in scripts\\leak.ps1",
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
        "sensitive credential container is not release-safe: certs\\private.key",
        "sensitive credential container is not release-safe: certs\\bundle.p12",
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

    assert failures == ["secret-like token in docs\\secrets.md"]


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

    assert failures == ["secret-like token in docs\\probe.md"]


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
        "production readiness claim in docs\\claims.md: production-ready"
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
        "docs\\evidence\\diploma_demo.json"
    ) in failures
    assert (
        "release evidence was generated from a dirty worktree: "
        "docs\\evidence\\diploma_demo.json"
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
    (root / "docs" / "eval_gate.md").write_text("# Eval\n", encoding="utf-8")
    (root / "docs" / "tool_sop.md").write_text(
        gate.build_tool_sop_markdown(),
        encoding="utf-8",
    )
    (root / "docs" / "openapi.json").write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "contracts" / "export_manifest.json").write_text("{}\n", encoding="utf-8")


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
