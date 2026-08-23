"""Validate exported Agent Coach contract artifacts.

The default check is public-CI friendly and needs only this repository. Passing
``--source-root`` additionally verifies source sha256 values against a private
HomeTutor checkout when one is available to a maintainer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "contracts" / "export_manifest.json"

_ALLOWED_TRANSFORMATIONS = {
    "none",
    "derived: deterministic public validation vector from exported contract bundle",
}
_LOCAL_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\\\"),
    re.compile("/" + "home/"),
    re.compile("/" + "Users/"),
)
_SECRET_MARKERS = (
    "s" + "k-",
    "PRIVATE" + " KEY",
    "Bearer" + " ",
    "BEGIN" + " OPENSSH",
)


class ContractExportError(RuntimeError):
    """Raised when the exported contract set is invalid."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ContractExportError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_relative_path(value: str, field: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ContractExportError(
            f"{field} must be a repository-relative path: {value}"
        )
    if "\\" in value:
        raise ContractExportError(f"{field} must use portable '/' separators: {value}")


def _assert_no_forbidden_content(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in _SECRET_MARKERS:
        if marker in text:
            raise ContractExportError(f"forbidden secret marker {marker!r} in {path}")
    for pattern in _LOCAL_PATH_PATTERNS:
        if pattern.search(text):
            raise ContractExportError(f"forbidden local path marker in {path}")


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    required = {
        "export_version",
        "source_repository",
        "source_git_commit",
        "contract_version",
        "contract_schema_hash",
        "files",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ContractExportError(f"manifest missing fields: {', '.join(missing)}")
    if manifest["source_repository"] != "hometutor":
        raise ContractExportError("source_repository must be hometutor")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest["source_git_commit"])):
        raise ContractExportError("source_git_commit must be a 40-character hex SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest["contract_schema_hash"])):
        raise ContractExportError("contract_schema_hash must be a sha256 hex digest")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise ContractExportError("manifest files must be a non-empty list")


def _validate_exported_bundle(bundle: dict[str, Any], manifest: dict[str, Any]) -> None:
    if bundle.get("schema_version") != manifest["contract_version"]:
        raise ContractExportError("bundle schema_version does not match manifest")
    payload = {
        "schema_version": bundle["schema_version"],
        "contracts": bundle["contracts"],
    }
    recomputed = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    if bundle.get("schema_hash") != recomputed:
        raise ContractExportError("bundle schema_hash is not canonical")
    if manifest["contract_schema_hash"] != recomputed:
        raise ContractExportError("manifest contract_schema_hash does not match bundle")


def _validate_vectors(
    vectors: dict[str, Any], bundle: dict[str, Any], contract_sha: str
) -> None:
    tools = bundle["contracts"]["tools"]
    all_tools = tools["read_only_default"] + tools["write_enabled_only"]
    expected_names = [tool["name"] for tool in all_tools]
    if vectors.get("contract_schema_version") != bundle["schema_version"]:
        raise ContractExportError("test vector schema version drift")
    if vectors.get("contract_schema_hash") != bundle["schema_hash"]:
        raise ContractExportError("test vector schema hash drift")
    if vectors.get("canonical_payload_sha256") != bundle["schema_hash"]:
        raise ContractExportError("test vector canonical payload hash drift")
    if vectors.get("exported_contract_sha256") != contract_sha:
        raise ContractExportError("test vector exported contract file hash drift")
    if vectors.get("tool_name_order") != expected_names:
        raise ContractExportError("test vector tool order drift")
    if vectors.get("default_read_only_tool_count") != len(tools["read_only_default"]):
        raise ContractExportError("test vector read-only tool count drift")
    if vectors.get("write_enabled_only_tool_count") != len(tools["write_enabled_only"]):
        raise ContractExportError("test vector write-only tool count drift")


def validate_export(
    manifest_path: Path = MANIFEST_PATH, source_root: Path | None = None
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    _validate_manifest_shape(manifest)
    _assert_no_forbidden_content(manifest_path)

    contract_bundle: dict[str, Any] | None = None
    vectors: dict[str, Any] | None = None
    contract_sha = ""
    seen_targets: set[str] = set()

    for entry in manifest["files"]:
        for field in ("source_path", "target_path"):
            value = entry.get(field)
            if not isinstance(value, str):
                raise ContractExportError(f"manifest entry {field} must be a string")
            _assert_relative_path(value, field)
        transformation = entry.get("transformation")
        if transformation not in _ALLOWED_TRANSFORMATIONS:
            raise ContractExportError(f"unsupported transformation: {transformation!r}")
        target_path = REPO_ROOT / entry["target_path"]
        if entry["target_path"] in seen_targets:
            raise ContractExportError(f"duplicate target path: {entry['target_path']}")
        seen_targets.add(entry["target_path"])
        if not target_path.exists():
            raise ContractExportError(f"missing exported file: {entry['target_path']}")
        target_sha = _sha256(target_path)
        if target_sha != entry.get("target_sha256"):
            raise ContractExportError(f"target hash drift: {entry['target_path']}")
        _assert_no_forbidden_content(target_path)

        if source_root is not None:
            source_path = source_root / entry["source_path"]
            if not source_path.exists():
                raise ContractExportError(
                    f"missing source file: {entry['source_path']}"
                )
            if _sha256(source_path) != entry.get("source_sha256"):
                raise ContractExportError(f"source hash drift: {entry['source_path']}")

        if entry["target_path"].endswith("agent_contract_bundle.json"):
            contract_bundle = _load_json(target_path)
            contract_sha = target_sha
        elif entry["target_path"].endswith("contract_test_vectors.json"):
            vectors = _load_json(target_path)

    if contract_bundle is None:
        raise ContractExportError(
            "manifest does not include agent_contract_bundle.json"
        )
    if vectors is None:
        raise ContractExportError(
            "manifest does not include contract_test_vectors.json"
        )
    _validate_exported_bundle(contract_bundle, manifest)
    _validate_vectors(vectors, contract_bundle, contract_sha)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="optional private HomeTutor checkout for source sha256 verification",
    )
    args = parser.parse_args(argv)

    try:
        manifest = validate_export(args.manifest, args.source_root)
    except ContractExportError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "OK: "
        f"{manifest['contract_version']} "
        f"schema_hash={manifest['contract_schema_hash']} "
        f"files={len(manifest['files'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
