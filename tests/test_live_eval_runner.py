from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import run_live_eval

from agent_coach.eval.live_evidence import (
    AUTONOMOUS_LIVE_EVAL_PUBLIC_SCHEMA_VERSION,
    AUTONOMOUS_LIVE_EVAL_THRESHOLDS,
    LIVE_EVAL_CASE_REGISTRY,
    LIVE_EVAL_PUBLIC_SCHEMA_VERSION,
    LIVE_EXECUTION_BACKEND,
    UNEXPECTED_PUBLIC_FIELD_FAILURE,
    UNSAFE_PUBLIC_VALUE_FAILURE,
    autonomous_live_eval_case_registry_hash,
    bounded_live_eval_failure,
    executable_case_contract,
    live_eval_case_registry_hash,
    live_eval_contract_hash,
    live_eval_corpus_hash,
    public_case_contract,
    validate_autonomous_live_eval_public_payload,
    validate_current_live_eval_public_payload,
    validate_historical_live_eval_public_payload,
    validate_live_eval_public_payload,
)
from agent_coach.provider.errors import ProviderAdapterError


def _external_wrapper_paths(tmp_path: Path, monkeypatch):
    repo = tmp_path / "checkout"
    repo.mkdir()
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", repo)
    return (
        tmp_path / "agent-coach-live-eval-public.json",
        tmp_path / "agent-coach-live-wrapper.json",
    )


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


def test_live_eval_requires_registered_rag_query_for_every_case(
    monkeypatch,
) -> None:
    original_build = run_live_eval.build_live_composition
    requirements = []

    def recording_build(*args, **kwargs):
        requirements.append(kwargs.get("tool_requirement"))
        return original_build(*args, **kwargs)

    monkeypatch.setattr(run_live_eval, "build_live_composition", recording_build)

    payload = run_live_eval.run_live_eval(scripted=True)

    assert payload["task_success_rate"] == 1.0
    assert len(requirements) == len(run_live_eval.LIVE_EVAL_CASES)
    for case, requirement in zip(
        run_live_eval.LIVE_EVAL_CASES,
        requirements,
        strict=True,
    ):
        assert requirement is not None
        assert requirement.name == "rag.search"
        assert requirement.arguments == {
            "query": case.search_query,
            "top_k": 2,
        }


def test_scripted_live_eval_cannot_emit_live_wrapper(tmp_path: Path, capsys) -> None:
    wrapper = tmp_path / "live-wrapper.json"

    assert run_live_eval.main(["--scripted", "--wrapper-output", str(wrapper)]) == 2

    assert "not live evidence" in capsys.readouterr().err
    assert not wrapper.exists()


def test_scripted_autonomous_eval_uses_auto_tool_choice_and_separate_schema(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    original_build = run_live_eval.build_live_composition
    requirements = []

    def recording_build(*args, **kwargs):
        requirements.append(kwargs.get("tool_requirement"))
        return original_build(*args, **kwargs)

    monkeypatch.setattr(run_live_eval, "build_live_composition", recording_build)
    output = tmp_path / "scripted-autonomous.json"

    assert (
        run_live_eval.main(
            ["--autonomous", "--scripted", "--output", str(output)]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == AUTONOMOUS_LIVE_EVAL_PUBLIC_SCHEMA_VERSION
    assert payload["schema_version"] != LIVE_EVAL_PUBLIC_SCHEMA_VERSION
    assert payload["contains_scripted_responses"] is True
    assert payload["provider_profile_opt_in"] is False
    assert requirements == [None] * len(
        run_live_eval.AUTONOMOUS_LIVE_EVAL_CASE_REGISTRY
    )
    assert payload["metrics"] == {
        "tool_name_accuracy": 1.0,
        "tool_name_case_count": 1,
        "no_call_precision": 1.0,
        "no_call_case_count": 2,
        "valid_args_rate": 1.0,
        "valid_args_case_count": 1,
        "invalid_forbidden_executions": 0,
    }
    assert validate_autonomous_live_eval_public_payload(
        payload,
        allow_scripted=True,
    ) == []
    assert validate_current_live_eval_public_payload(payload) == [
        "public live evidence has unexpected fields"
    ]


def test_autonomous_metrics_and_thresholds_fail_closed() -> None:
    payload = run_live_eval.run_autonomous_live_eval(scripted=True)
    assert payload["case_registry_hash"] == autonomous_live_eval_case_registry_hash()

    drifted_metrics = dict(payload)
    drifted_metrics["metrics"] = dict(payload["metrics"], no_call_precision=0.0)
    assert "autonomous metrics do not match per-case results" in (
        validate_autonomous_live_eval_public_payload(
            drifted_metrics,
            allow_scripted=True,
        )
    )

    drifted_thresholds = dict(payload)
    drifted_thresholds["thresholds"] = dict(
        AUTONOMOUS_LIVE_EVAL_THRESHOLDS,
        tool_name_accuracy=0.5,
    )
    assert "autonomous thresholds do not match the registry" in (
        validate_autonomous_live_eval_public_payload(
            drifted_thresholds,
            allow_scripted=True,
        )
    )


def test_live_eval_requires_explicit_network_and_provider_opt_in(capsys) -> None:
    assert run_live_eval.main([]) == 2

    assert "--allow-network and --provider-opt-in" in capsys.readouterr().err


def test_provider_failure_result_preserves_valid_eighty_percent_evidence(
    tmp_path: Path, monkeypatch, capsys
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
    current_failures = validate_current_live_eval_public_payload(payload)
    assert current_failures
    assert any("scripted" in item for item in current_failures)

    public_artifact, wrapper = _external_wrapper_paths(tmp_path, monkeypatch)
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_live_eval, "_git_commit", lambda: "reviewed-head")

    assert run_live_eval.main(
        [
            "--wrapper-only",
            "--public-artifact",
            str(public_artifact),
            "--wrapper-output",
            str(wrapper),
        ]
    ) == 2
    stderr = capsys.readouterr().err
    assert "invalid public artifact:" in stderr
    assert not wrapper.exists()


def test_wrapper_only_hashes_existing_public_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    public_artifact, wrapper = _external_wrapper_paths(tmp_path, monkeypatch)
    commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    payload = _current_live_public_payload(commit=commit)
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_live_eval, "_git_commit", lambda: commit)
    monkeypatch.setattr(run_live_eval, "_git_worktree_clean", lambda: True)

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                str(public_artifact),
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 0
    )

    written = json.loads(wrapper.read_text(encoding="utf-8"))
    assert written["schema_version"] == "agent-coach-live-eval-evidence/1.0.0"
    assert written["commit"] == commit
    assert written["evidence_artifacts"] == [
        {
            "label": "agent-coach-live-eval-public.json",
            "sha256": hashlib.sha256(public_artifact.read_bytes()).hexdigest(),
        }
    ]


def test_wrapper_only_rejects_scripted_public_artifact(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    public_artifact, wrapper = _external_wrapper_paths(tmp_path, monkeypatch)
    public_artifact.write_text(
        json.dumps(run_live_eval.run_live_eval(scripted=True), indent=2) + "\n",
        encoding="utf-8",
    )

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                str(public_artifact),
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
    public_artifact, wrapper = _external_wrapper_paths(tmp_path, monkeypatch)
    payload = run_live_eval.run_live_eval(scripted=True)
    payload["mode"] = "live_provider"
    payload["contains_scripted_responses"] = False
    payload["provider_profile_opt_in"] = True
    payload["padding"] = "x" * 80_000
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                str(public_artifact),
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 2
    )

    assert "exceeds 64000 bytes" in capsys.readouterr().err
    assert not wrapper.exists()


def test_canonical_live_eval_registry_is_shared_and_hashed() -> None:
    assert run_live_eval.LIVE_EVAL_CASES is LIVE_EVAL_CASE_REGISTRY
    payload = run_live_eval.run_live_eval(scripted=True)
    assert payload["case_registry_hash"] == live_eval_case_registry_hash()
    assert payload["contract_hash"] == live_eval_contract_hash()
    assert payload["corpus_hash"] == live_eval_corpus_hash()
    assert payload["execution_backend"] == "scripted_responses_client"
    drifted = dict(payload)
    drifted["case_registry_hash"] = "0" * 64
    assert any(
        "case_registry_hash does not match the registry" in item
        for item in validate_current_live_eval_public_payload(drifted)
    )
    case = LIVE_EVAL_CASE_REGISTRY[0]
    assert "search_query" not in public_case_contract(case)
    assert "scripted_answer" not in public_case_contract(case)
    assert executable_case_contract(case)["search_query"] == case.search_query
    assert executable_case_contract(case)["scripted_answer"] == case.scripted_answer
    public_only = hashlib.sha256(
        json.dumps(
            [public_case_contract(item) for item in LIVE_EVAL_CASE_REGISTRY],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert live_eval_case_registry_hash() != public_only


def test_scripted_payload_stays_rejected_after_one_flag_flip() -> None:
    payload = run_live_eval.run_live_eval(scripted=True)
    for field_name, value in (
        ("contains_scripted_responses", False),
        ("mode", "live_provider"),
        ("provider_profile_opt_in", True),
        ("execution_backend", LIVE_EXECUTION_BACKEND),
        ("clean_worktree", True),
    ):
        mutated = dict(payload)
        mutated[field_name] = value
        failures = validate_current_live_eval_public_payload(mutated)
        assert failures, field_name


def test_current_validator_rejects_other_commit_and_dirty_run() -> None:
    commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    other = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    payload = _current_live_public_payload(commit=commit)
    assert (
        validate_current_live_eval_public_payload(payload, expected_commit=commit)
        == []
    )

    dirty = dict(payload)
    dirty["clean_worktree"] = False
    assert "clean worktree" in " ".join(
        validate_current_live_eval_public_payload(dirty, expected_commit=commit)
    )
    assert any(
        "does not match expected commit" in item
        for item in validate_current_live_eval_public_payload(
            payload, expected_commit=other
        )
    )


def test_wrapper_only_rejects_historical_example(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    evidence_dir = tmp_path / "docs" / "evidence" / "historical"
    evidence_dir.mkdir(parents=True)
    public_artifact = evidence_dir / "live-eval-public.json"
    payload = _current_live_public_payload()
    payload["provenance"] = {
        "classification": "historical_example",
        "contains_credentials": False,
        "contains_learner_data": False,
        "contains_hometutor_runtime_dependency": False,
        "contains_raw_provider_payloads": False,
    }
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.json"
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        run_live_eval, "_git_commit", lambda: payload["evaluated_commit"]
    )

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                "docs/evidence/historical/live-eval-public.json",
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 2
    )
    assert "historical example is not current live evidence" in capsys.readouterr().err
    assert not wrapper.exists()


def test_historical_example_is_not_current_live_evidence() -> None:
    payload = _current_live_public_payload()
    payload["provenance"] = {
        "classification": "historical_example",
        "contains_credentials": False,
        "contains_learner_data": False,
        "contains_hometutor_runtime_dependency": False,
        "contains_raw_provider_payloads": False,
    }
    payload["historical_evaluated_commit"] = "829df29e58f6dd48fb09ee1400dec3c4115ad6b9"
    assert validate_historical_live_eval_public_payload(payload) == []
    assert validate_current_live_eval_public_payload(payload) == [
        "historical example is not current live evidence"
    ]


def test_live_eval_rejects_in_checkout_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", tmp_path)
    output = tmp_path / "docs" / "evidence" / "live-eval-public.json"
    output.parent.mkdir(parents=True)

    assert (
        run_live_eval.main(
            [
                "--allow-network",
                "--provider-opt-in",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert "written outside the checkout" in capsys.readouterr().err
    assert not output.exists()


def test_current_validator_rejects_unexpected_secret_fields() -> None:
    payload = _current_live_public_payload()
    payload["raw_provider_payload"] = {"api_key": "example-not-a-secret"}
    assert validate_current_live_eval_public_payload(payload) == [
        UNEXPECTED_PUBLIC_FIELD_FAILURE
    ]


def test_current_validator_rejects_secret_in_allowed_identifier() -> None:
    payload = _current_live_public_payload()
    payload["model_projection"]["planner"]["backend"] = "sk-proj-EXAMPLE"
    assert validate_current_live_eval_public_payload(payload) == [
        UNSAFE_PUBLIC_VALUE_FAILURE
    ]


def test_current_validator_rejects_raw_provider_grammar_in_error() -> None:
    payload = _current_live_public_payload()
    payload["results"][0]["error"] = (
        "raw_provider_payload response_id resp_123 output message"
    )
    assert validate_current_live_eval_public_payload(payload) == [
        UNSAFE_PUBLIC_VALUE_FAILURE
    ]


def test_current_validator_rejects_oversized_dynamic_error() -> None:
    payload = _current_live_public_payload()
    payload["results"][0]["error"] = "x" * 10000
    assert validate_current_live_eval_public_payload(payload) == [
        UNSAFE_PUBLIC_VALUE_FAILURE
    ]


def test_wrapper_only_rejects_in_checkout_current_artifact(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "checkout"
    repo.mkdir()
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", repo)
    public_artifact = repo / "docs" / "evidence" / "live-eval-public.json"
    public_artifact.parent.mkdir(parents=True)
    public_artifact.write_text("{}\n", encoding="utf-8")
    wrapper = tmp_path / "agent-coach-live-wrapper.json"

    assert run_live_eval._public_artifact_label(public_artifact) is None
    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                str(public_artifact),
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 2
    )
    assert "written outside the checkout" in capsys.readouterr().err
    assert not wrapper.exists()


def test_wrapper_only_rejects_in_checkout_wrapper_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    public_artifact, _unused_wrapper = _external_wrapper_paths(tmp_path, monkeypatch)
    public_artifact.write_text("{}\n", encoding="utf-8")
    wrapper = run_live_eval.REPO_ROOT / "docs" / "wrapper.json"

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                str(public_artifact),
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 2
    )
    assert "written outside the checkout" in capsys.readouterr().err
    assert not wrapper.exists()


def test_wrapper_only_rejects_dirty_worktree(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    public_artifact, wrapper = _external_wrapper_paths(tmp_path, monkeypatch)
    commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    payload = _current_live_public_payload(commit=commit)
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_live_eval, "_git_commit", lambda: commit)
    monkeypatch.setattr(run_live_eval, "_git_worktree_clean", lambda: False)

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                str(public_artifact),
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 2
    )
    assert "clean worktree" in capsys.readouterr().err
    assert not wrapper.exists()


def test_wrapper_post_check_failure_does_not_leave_evidence_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    public_artifact, wrapper = _external_wrapper_paths(tmp_path, monkeypatch)
    commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    payload = _current_live_public_payload(commit=commit)
    public_artifact.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_live_eval, "_git_commit", lambda: commit)
    states = iter((True, False))
    monkeypatch.setattr(run_live_eval, "_git_worktree_clean", lambda: next(states))

    assert (
        run_live_eval.main(
            [
                "--wrapper-only",
                "--public-artifact",
                str(public_artifact),
                "--wrapper-output",
                str(wrapper),
            ]
        )
        == 2
    )
    assert "clean worktree" in capsys.readouterr().err
    assert not wrapper.exists()
    assert not wrapper.with_name(f"{wrapper.name}.partial").exists()


def test_live_output_post_check_failure_does_not_leave_evidence_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "checkout"
    repo.mkdir()
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", repo)
    output = tmp_path / "agent-coach-live-eval-public.json"
    commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    payload = _current_live_public_payload(commit=commit)
    monkeypatch.setattr(run_live_eval, "run_live_eval", lambda scripted=False: payload)
    monkeypatch.setattr(run_live_eval, "_git_commit", lambda: commit)
    states = iter((True, False))
    monkeypatch.setattr(run_live_eval, "_git_worktree_clean", lambda: next(states))

    assert (
        run_live_eval.main(
            [
                "--allow-network",
                "--provider-opt-in",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert "clean worktree" in capsys.readouterr().err
    assert not output.exists()
    assert not output.with_name(f"{output.name}.partial").exists()


def test_live_relative_output_resolves_against_repo_root_not_cwd(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "checkout"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", repo)
    monkeypatch.chdir(scripts)
    commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    payload = _current_live_public_payload(commit=commit)
    monkeypatch.setattr(run_live_eval, "run_live_eval", lambda scripted=False: payload)
    monkeypatch.setattr(run_live_eval, "_git_commit", lambda: commit)
    monkeypatch.setattr(run_live_eval, "_git_worktree_clean", lambda: True)
    relative = Path("..") / "docs" / "evidence" / "live-eval-public.json"
    inside = repo / "docs" / "evidence" / "live-eval-public.json"
    outside = (repo / relative).resolve()

    assert (
        run_live_eval.main(
            [
                "--allow-network",
                "--provider-opt-in",
                "--output",
                str(relative),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert not inside.exists()
    assert outside.is_file()


def test_live_relative_in_checkout_output_is_rejected_from_subdirectory(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "checkout"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    monkeypatch.setattr(run_live_eval, "REPO_ROOT", repo)
    monkeypatch.chdir(scripts)
    relative = Path("docs") / "evidence" / "live-eval-public.json"

    assert (
        run_live_eval.main(
            [
                "--allow-network",
                "--provider-opt-in",
                "--output",
                str(relative),
            ]
        )
        == 2
    )
    assert "written outside the checkout" in capsys.readouterr().err
    assert not (repo / relative).exists()
    assert not (scripts / relative).exists()


def test_provenance_failure_is_bounded() -> None:
    failure = bounded_live_eval_failure(["x" * 400, "second"])
    assert len(failure) <= 240
    assert "second" not in failure


def _current_live_public_payload(
    *, commit: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
) -> dict[str, object]:
    payload = run_live_eval.run_live_eval(scripted=True)
    payload["mode"] = "live_provider"
    payload["contains_scripted_responses"] = False
    payload["provider_profile_opt_in"] = True
    payload["execution_backend"] = LIVE_EXECUTION_BACKEND
    payload["evaluated_commit"] = commit
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
