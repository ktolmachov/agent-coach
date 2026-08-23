from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_drift_gate.py"
HOMETUTOR_ROOT = REPO_ROOT.parent / "hometutor"
CONTRACT_PATH = (
    REPO_ROOT
    / "contracts"
    / "agent_contracts"
    / "v1"
    / "agent_contract_bundle.json"
)
MANIFEST_PATH = REPO_ROOT / "contracts" / "export_manifest.json"
SOURCE_CONTRACT_PATH = "docs/schemas/agent_contracts/v1/agent_contract_bundle.json"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_drift_gate", CHECKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_drift_gate_report_is_fail_closed_and_ci_independent() -> None:
    checker = _load_checker()

    report = checker.build_report()

    assert report["contract_hash_equal_to_manifest"] is True
    assert report["source_verification"]["mode"] == "public_ci"
    assert report["public_ci_independent_of_hometutor"] is True
    assert report["source_provenance_complete"] is True
    assert report["semantic_subset"]["ratio"] >= 0.95
    assert report["security_assertions"]["ratio"] == 1.0
    assert report["runtime_absolute_path_dependency"]["offenders"] == []


def test_drift_gate_cli_runs_without_hometutor_checkout() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER_PATH)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "source=public_ci" in result.stdout
    assert "semantic=11/11" in result.stdout
    assert "security=5/5" in result.stdout


def test_optional_cross_repo_source_verification_matches_current_hometutor() -> None:
    checker = _load_checker()
    if not (HOMETUTOR_ROOT / ".git").exists():
        pytest.skip("HomeTutor checkout is unavailable")

    report = checker.build_report(HOMETUTOR_ROOT)

    assert report["source_verification"]["mode"] == "cross_repo"
    assert report["source_verification"]["checked"] is True
    assert report["source_verification"]["schema_hash_equal"] is True
    assert report["public_ci_independent_of_hometutor"] is False


def test_drift_gate_rejects_semantic_corruption(monkeypatch) -> None:
    checker = _load_checker()
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from agent_coach.core.runner import AgentRunner

    original_run = AgentRunner.run

    def corrupted_run(self, request):
        result = original_run(self, request)
        result.answer = "SEMANTICALLY WRONG ANSWER"
        result.sources = []
        return result

    monkeypatch.setattr(AgentRunner, "run", corrupted_run)

    with pytest.raises(checker.DriftGateError, match="semantic subset"):
        checker.build_report()


def test_drift_gate_rejects_shared_helper_projection_drift(monkeypatch) -> None:
    checker = _load_checker()
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from agent_coach.core import security

    original_compact = security.compact_tool_result

    def drifted_compact_tool_result(result, *, max_chars):
        compact = original_compact(result, max_chars=max_chars)
        compact.meta["unexpected_public_field"] = "drift"
        return compact

    monkeypatch.setattr(security, "compact_tool_result", drifted_compact_tool_result)

    with pytest.raises(checker.DriftGateError, match="semantic subset"):
        checker.build_report()


def test_drift_gate_rejects_fixture_golden_scenario_set_drift(monkeypatch) -> None:
    checker = _load_checker()
    sys.path.insert(0, str(REPO_ROOT / "src"))
    import agent_coach.mock.fixtures as fixtures

    original_load = fixtures.load_mock_fixture

    def load_without_fake_secret(path=None):
        fixture = original_load(path)
        scenarios = dict(fixture.scenarios)
        scenarios.pop("fake_secret")
        return fixtures.MockFixture(
            schema_version=fixture.schema_version,
            provenance=fixture.provenance,
            advertised_read_only_tools=fixture.advertised_read_only_tools,
            controlled_outcomes=fixture.controlled_outcomes,
            scenarios=scenarios,
        )

    monkeypatch.setattr(fixtures, "load_mock_fixture", load_without_fake_secret)
    monkeypatch.setattr("agent_coach.mock.load_mock_fixture", load_without_fake_secret)

    with pytest.raises(checker.DriftGateError, match="semantic scenario set drift"):
        checker.build_report()


def test_drift_gate_rejects_invalid_golden_hash(monkeypatch) -> None:
    checker = _load_checker()

    def invalid_hashes(path=checker.GOLDEN_PROJECTIONS_PATH):
        return {"grounded_success": "not-a-sha256"}

    monkeypatch.setattr(checker, "_load_golden_projection_hashes", invalid_hashes)

    with pytest.raises(checker.DriftGateError, match="semantic scenario set drift"):
        checker.build_report()


def test_golden_hash_loader_rejects_invalid_hash_encoding(tmp_path) -> None:
    checker = _load_checker()
    payload = {
        "schema_version": checker.GOLDEN_PROJECTIONS_VERSION,
        "scenarios": {"grounded_success": "A" * 64},
    }
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(checker.DriftGateError, match="invalid golden projection hash"):
        checker._load_golden_projection_hashes(path)


def test_runtime_dependency_scan_catches_common_private_path_forms(tmp_path) -> None:
    checker = _load_checker()
    (tmp_path / "known_hit.py").write_text(
        'PRIVATE_PATH = r"D:\\Projects\\hometutor\\secret.md"\n',
        encoding="utf-8",
    )
    (tmp_path / "forward_slash.json").write_text(
        '{"path": "D:/Projects/hometutor/secret.md"}\n',
        encoding="utf-8",
    )
    (tmp_path / "unc.toml").write_text(
        'path = "\\\\\\\\server\\\\share\\\\private.txt"\n',
        encoding="utf-8",
    )
    (tmp_path / "posix.json").write_text(
        '{"path": "/opt/private/agent-coach.json"}\n',
        encoding="utf-8",
    )
    (tmp_path / "file_uri.yaml").write_text(
        "path: file:///tmp/agent-coach-private.json\n",
        encoding="utf-8",
    )
    (tmp_path / "root.json").write_text(
        '{"path": "/root/hometutor/secret.json"}\n',
        encoding="utf-8",
    )
    (tmp_path / "workspace.json").write_text(
        '{"path": "/workspace/hometutor/secret.json"}\n',
        encoding="utf-8",
    )
    (tmp_path / "srv.json").write_text(
        '{"path": "/srv/hometutor/secret.json"}\n',
        encoding="utf-8",
    )
    (tmp_path / "app.json").write_text(
        '{"path": "/app/hometutor/private.md"}\n',
        encoding="utf-8",
    )
    (tmp_path / "data.json").write_text(
        '{"path": "/data/hometutor/private.md"}\n',
        encoding="utf-8",
    )
    (tmp_path / "workspaces.json").write_text(
        '{"path": "/workspaces/hometutor/private.md"}\n',
        encoding="utf-8",
    )
    (tmp_path / "repo.json").write_text(
        '{"path": "/repo/hometutor/private.md"}\n',
        encoding="utf-8",
    )
    (tmp_path / "url_then_private.json").write_text(
        '{"mixed": "https://example.com/docs,D:/Projects/hometutor/secret.md"}\n',
        encoding="utf-8",
    )
    (tmp_path / "semicolon_then_private.json").write_text(
        '{"mixed": "https://example.com/docs;D:/Projects/hometutor/secret.md"}\n',
        encoding="utf-8",
    )
    (tmp_path / "bracketed_path.py").write_text(
        'PRIVATE_PATH = r"D:\\Projects\\hometutor\\[draft]\\secret.md"\n',
        encoding="utf-8",
    )
    (tmp_path / "split_drive.py").write_text(
        'PRIVATE = "D:" + "/Projects/hometutor/private.md"\n',
        encoding="utf-8",
    )
    (tmp_path / "split_posix.py").write_text(
        'PRIVATE = "/root" + "/hometutor/private.md"\n',
        encoding="utf-8",
    )
    (tmp_path / "public_url.json").write_text(
        '{"url": "https://example.com/opt/private/agent-coach.json"}\n',
        encoding="utf-8",
    )

    report = checker._runtime_dependency_report((tmp_path,))

    assert set(report["offenders"]) == {
        (tmp_path / "file_uri.yaml").as_posix(),
        (tmp_path / "forward_slash.json").as_posix(),
        (tmp_path / "known_hit.py").as_posix(),
        (tmp_path / "posix.json").as_posix(),
        (tmp_path / "root.json").as_posix(),
        (tmp_path / "workspace.json").as_posix(),
        (tmp_path / "srv.json").as_posix(),
        (tmp_path / "app.json").as_posix(),
        (tmp_path / "data.json").as_posix(),
        (tmp_path / "workspaces.json").as_posix(),
        (tmp_path / "repo.json").as_posix(),
        (tmp_path / "url_then_private.json").as_posix(),
        (tmp_path / "semicolon_then_private.json").as_posix(),
        (tmp_path / "bracketed_path.py").as_posix(),
        (tmp_path / "split_drive.py").as_posix(),
        (tmp_path / "split_posix.py").as_posix(),
        (tmp_path / "unc.toml").as_posix(),
    }


def test_drift_gate_cli_rejects_manifest_contract_hash_drift(tmp_path) -> None:
    mutated = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    mutated["contract_schema_hash"] = "0" * 64
    tmp_manifest = tmp_path / "export_manifest.json"
    tmp_manifest.write_text(
        json.dumps(mutated, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER_PATH),
            "--manifest",
            str(tmp_manifest),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stderr.startswith("FAIL: ")
    assert "contract_schema_hash does not match bundle" in result.stderr


def test_drift_gate_cli_rejects_malformed_contract_bundle_without_traceback(
    tmp_path,
) -> None:
    bundle_path = tmp_path / "agent_contract_bundle.json"
    bundle_path.write_text("{not-json", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER_PATH),
            "--contract-bundle",
            str(bundle_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stderr.startswith("FAIL: ")
    assert "Traceback" not in result.stderr
    assert "malformed JSON" in result.stderr


def test_drift_gate_cli_rejects_contract_bundle_missing_required_fields(
    tmp_path,
) -> None:
    bundle_path = tmp_path / "agent_contract_bundle.json"
    bundle_path.write_text(
        '{"schema_version": "agent-contracts/1.0.0"}\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER_PATH),
            "--contract-bundle",
            str(bundle_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stderr.startswith("FAIL: ")
    assert "Traceback" not in result.stderr
    assert "contract bundle missing field" in result.stderr


def test_cross_repo_mode_rejects_current_source_contract_drift(tmp_path) -> None:
    checker = _load_checker()
    source_root = tmp_path / "source"
    source_file = source_root / SOURCE_CONTRACT_PATH
    source_file.parent.mkdir(parents=True)
    contract_bytes = CONTRACT_PATH.read_bytes()
    source_file.write_bytes(contract_bytes)
    _git(source_root, "init")
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-m", "source contract baseline")
    baseline_commit = _git(source_root, "rev-parse", "HEAD").stdout.strip()

    current = json.loads(source_file.read_text(encoding="utf-8"))
    current["contracts"]["current_vs_deferred"]["current_embedded"] = "drifted"
    source_file.write_text(
        json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-m", "drift source contract")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["source_git_commit"] = baseline_commit
    source_sha = hashlib.sha256(contract_bytes).hexdigest()
    for entry in manifest["files"]:
        entry["source_sha256"] = source_sha
    tmp_manifest = tmp_path / "export_manifest.json"
    tmp_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        checker.DriftGateError,
        match="current HomeTutor contract schema hash drift",
    ):
        checker.build_report(source_root, manifest_path=tmp_manifest)


def test_cross_repo_mode_rejects_malformed_current_source_contract(
    tmp_path,
) -> None:
    checker = _load_checker()
    source_root = tmp_path / "source"
    source_file = source_root / SOURCE_CONTRACT_PATH
    source_file.parent.mkdir(parents=True)
    contract_bytes = CONTRACT_PATH.read_bytes()
    source_file.write_bytes(contract_bytes)
    _git(source_root, "init")
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-m", "source contract baseline")
    baseline_commit = _git(source_root, "rev-parse", "HEAD").stdout.strip()

    source_file.write_text("{not-json", encoding="utf-8")
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-m", "malformed source contract")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["source_git_commit"] = baseline_commit
    source_sha = hashlib.sha256(contract_bytes).hexdigest()
    for entry in manifest["files"]:
        entry["source_sha256"] = source_sha
    tmp_manifest = tmp_path / "export_manifest.json"
    tmp_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        checker.DriftGateError,
        match="current source contract bundle is malformed",
    ):
        checker.build_report(source_root, manifest_path=tmp_manifest)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Agent Coach Test",
            "-c",
            "user.email=agent-coach@example.test",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
