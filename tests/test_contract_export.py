from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_contract_export.py"
MANIFEST_PATH = REPO_ROOT / "contracts" / "export_manifest.json"
CONTRACT_HASH = "218c90732c25ae2f9b26c4f5a9ea5ee81c28bf797299c99b53e310bf22315910"
CONTRACT_PATH = REPO_ROOT / "contracts" / "agent_contracts" / "v1"
CONTRACT_PATH = CONTRACT_PATH / "agent_contract_bundle.json"
SOURCE_COMMIT = "292be74f97b18615388838c2a1ddf2e0879585e0"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_contract_export", CHECKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_export_manifest_is_complete_and_hash_stable() -> None:
    checker = _load_checker()
    manifest = checker.validate_export(MANIFEST_PATH)

    assert manifest["source_repository"] == "hometutor"
    assert manifest["source_git_commit"] == SOURCE_COMMIT
    assert manifest["contract_version"] == "agent-contracts/1.0.0"
    assert manifest["contract_schema_hash"] == CONTRACT_HASH
    assert {entry["target_path"] for entry in manifest["files"]} == {
        "contracts/agent_contracts/v1/agent_contract_bundle.json",
        "contracts/agent_contracts/v1/contract_test_vectors.json",
    }


def test_exported_contract_bundle_is_public_ci_validatable() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER_PATH)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"schema_hash={CONTRACT_HASH}" in result.stdout


def test_d2_export_vector_and_manifest_are_byte_stable() -> None:
    contract_bytes = CONTRACT_PATH.read_bytes()
    bundle = json.loads(contract_bytes.decode("utf-8"))
    tools = bundle["contracts"]["tools"]
    all_tools = tools["read_only_default"] + tools["write_enabled_only"]
    payload = {
        "schema_version": bundle["schema_version"],
        "contracts": bundle["contracts"],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    harness_fields = bundle["contracts"]["tool_context"]["harness_only_fields"]
    vector_payload = {
        "schema_version": "agent-contract-test-vectors/1.0.0",
        "contract_schema_version": bundle["schema_version"],
        "contract_schema_hash": bundle["schema_hash"],
        "canonical_payload_sha256": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
        "exported_contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "tool_name_order": [tool["name"] for tool in all_tools],
        "default_read_only_tool_count": len(tools["read_only_default"]),
        "write_enabled_only_tool_count": len(tools["write_enabled_only"]),
        "harness_only_fields": harness_fields,
        "forbidden_model_arg_fields": sorted([*harness_fields, "scopes"]),
    }
    vector_path = REPO_ROOT / "contracts" / "agent_contracts" / "v1"
    vector_path = vector_path / "contract_test_vectors.json"
    vector_text = json.dumps(
        vector_payload, ensure_ascii=False, sort_keys=True, indent=2
    )
    assert vector_path.read_text(encoding="utf-8") == vector_text + "\n"

    vector_sha = hashlib.sha256(vector_path.read_bytes()).hexdigest()
    source_sha = hashlib.sha256(contract_bytes).hexdigest()
    source_path = "docs/schemas/agent_contracts/v1/agent_contract_bundle.json"
    bundle_target = "contracts/agent_contracts/v1/agent_contract_bundle.json"
    vector_target = "contracts/agent_contracts/v1/contract_test_vectors.json"
    manifest_payload = {
        "export_version": "agent-coach-contract-export/1.0.0",
        "source_repository": "hometutor",
        "source_git_commit": SOURCE_COMMIT,
        "contract_version": bundle["schema_version"],
        "contract_schema_hash": bundle["schema_hash"],
        "files": [
            {
                "source_path": source_path,
                "target_path": bundle_target,
                "source_sha256": source_sha,
                "target_sha256": source_sha,
                "transformation": "none",
            },
            {
                "source_path": source_path,
                "target_path": vector_target,
                "source_sha256": source_sha,
                "target_sha256": vector_sha,
                "transformation": (
                    "derived: deterministic public validation vector from "
                    "exported contract bundle"
                ),
            },
        ],
    }
    manifest_text = json.dumps(
        manifest_payload, ensure_ascii=False, sort_keys=True, indent=2
    )
    assert MANIFEST_PATH.read_text(encoding="utf-8") == manifest_text + "\n"


def test_exported_contracts_do_not_depend_on_hometutor_imports() -> None:
    bundle = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert bundle["schema_version"] == "agent-contracts/1.0.0"
    serialized = json.dumps(bundle, ensure_ascii=False)
    for forbidden in ("from " + "app.", "import " + "app."):
        assert forbidden not in serialized
