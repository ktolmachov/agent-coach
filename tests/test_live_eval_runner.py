from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import run_live_eval

from agent_coach.eval.live_evidence import validate_live_eval_public_payload
from agent_coach.provider.errors import ProviderAdapterError


def test_scripted_live_eval_runner_validates_cases_without_live_wrapper(
    tmp_path: Path, capsys
) -> None:
    output = tmp_path / "scripted-live.json"

    assert run_live_eval.main(["--scripted", "--output", str(output)]) == 0

    stdout = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == stdout
    assert written["mode"] == "scripted_provider_contract"
    assert written["contains_scripted_responses"] is True
    assert written["provider_profile_opt_in"] is False
    assert written["case_count"] == 5
    assert written["task_success_rate"] == 1.0
    assert {result["answer_status"] for result in written["results"]} == {"grounded"}


def test_scripted_live_eval_cannot_emit_live_wrapper(tmp_path: Path, capsys) -> None:
    wrapper = tmp_path / "live-wrapper.json"

    assert run_live_eval.main(["--scripted", "--wrapper-output", str(wrapper)]) == 2

    assert "not live evidence" in capsys.readouterr().err
    assert not wrapper.exists()


def test_live_eval_requires_explicit_network_and_provider_opt_in(capsys) -> None:
    assert run_live_eval.main([]) == 2

    assert "--allow-network and --provider-opt-in" in capsys.readouterr().err


def test_provider_failure_result_preserves_valid_eighty_percent_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    original_build = run_live_eval.build_live_composition

    def fail_first_case(*args, **kwargs):
        if kwargs.get("run_id") == "live-eval-live-photosynthesis-grounded":
            raise ProviderAdapterError("rate_limit", "rate limit")
        return original_build(*args, **kwargs)

    monkeypatch.setattr(run_live_eval, "build_live_composition", fail_first_case)

    payload = run_live_eval.run_live_eval(scripted=True)

    assert payload["task_success_rate"] == 0.8
    assert payload["results"][0]["task_success"] is False
    assert payload["results"][0]["stop_reason"] == "rate_limit"
    assert payload["results"][0]["security"]["security_failures"] == 0

    payload["mode"] = "live_provider"
    payload["contains_scripted_responses"] = False
    payload["provider_profile_opt_in"] = True
    assert validate_live_eval_public_payload(payload) == []

    evidence_dir = tmp_path / "docs" / "evidence"
    evidence_dir.mkdir(parents=True)
    public_artifact = evidence_dir / "live-eval-public.json"
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.json"
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_live_eval, "_git_commit", lambda: "reviewed-head")

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                "docs/evidence/live-eval-public.json",
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 0
    )


def test_wrapper_only_hashes_existing_public_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    evidence_dir = tmp_path / "docs" / "evidence"
    evidence_dir.mkdir(parents=True)
    public_artifact = evidence_dir / "live-eval-public.json"
    payload = run_live_eval.run_live_eval(scripted=True)
    payload["mode"] = "live_provider"
    payload["contains_scripted_responses"] = False
    payload["provider_profile_opt_in"] = True
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.json"
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_live_eval, "_git_commit", lambda: "reviewed-head")

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                "docs/evidence/live-eval-public.json",
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 0
    )

    written = json.loads(wrapper.read_text(encoding="utf-8"))
    assert written["schema_version"] == "agent-coach-live-eval-evidence/1.0.0"
    assert written["commit"] == "reviewed-head"
    assert written["evidence_artifacts"] == [
        {
            "label": "docs/evidence/live-eval-public.json",
            "sha256": hashlib.sha256(public_artifact.read_bytes()).hexdigest(),
        }
    ]


def test_wrapper_only_rejects_scripted_public_artifact(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    evidence_dir = tmp_path / "docs" / "evidence"
    evidence_dir.mkdir(parents=True)
    public_artifact = evidence_dir / "live-eval-public.json"
    public_artifact.write_text(
        json.dumps(run_live_eval.run_live_eval(scripted=True), indent=2) + "\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.json"
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", tmp_path)

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                "docs/evidence/live-eval-public.json",
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 2
    )

    assert "scripted responses are not live evidence" in capsys.readouterr().err
    assert not wrapper.exists()


def test_wrapper_only_rejects_oversized_public_artifact(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    evidence_dir = tmp_path / "docs" / "evidence"
    evidence_dir.mkdir(parents=True)
    public_artifact = evidence_dir / "live-eval-public.json"
    payload = run_live_eval.run_live_eval(scripted=True)
    payload["mode"] = "live_provider"
    payload["contains_scripted_responses"] = False
    payload["provider_profile_opt_in"] = True
    payload["padding"] = "x" * 80_000
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.json"
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", tmp_path)

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                "docs/evidence/live-eval-public.json",
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 2
    )

    assert "exceeds 64000 bytes" in capsys.readouterr().err
    assert not wrapper.exists()
