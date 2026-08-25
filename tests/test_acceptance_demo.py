from __future__ import annotations

import socket
import subprocess

from scripts import run_acceptance_demo as acceptance


def test_command_plan_is_offline_and_covers_acceptance_surfaces() -> None:
    default_plan = acceptance.command_plan(full_checks=False)
    full_plan = acceptance.command_plan(full_checks=True)
    default_keys = {step.key for step in default_plan}
    full_keys = {step.key for step in full_plan}
    encoded = " ".join(arg for step in full_plan for arg in step.args)

    assert default_keys == {
        "package_artifact",
        "contract_export",
        "openapi_snapshot",
        "drift_gate",
        "public_release",
        "offline_eval",
        "mock_profile",
        "scripted_provider",
    }
    assert full_keys == default_keys | {"full_tests", "ruff", "compileall"}
    assert "--scripted" in encoded
    assert "--allow-network" not in encoded
    assert "--provider-opt-in" not in encoded


def test_local_vector_acceptance_step_is_grounded() -> None:
    step = acceptance._run_local_vector_demo()

    assert step.status == "PASS"
    assert "grounded=True" in step.summary
    assert "source=" in step.summary
    assert "cost=local_zero" in step.summary


def test_live_localhost_api_acceptance_smoke() -> None:
    port = _free_port()
    steps, process = acceptance._start_and_smoke_api(port)
    try:
        (
            api_step,
            chain_step,
            contrast_step,
            reproducibility_step,
            fail_closed_step,
        ) = steps
        assert api_step.status == "PASS"
        assert "health=ok" in api_step.summary
        assert "runs=3" in api_step.summary
        assert chain_step.status == "PASS"
        assert chain_step.evidence == {
            "question": "Explain photosynthesis and suggest practice.",
            "selected_tools": [
                "learner.get_profile",
                "rag.search",
                "quiz.generate",
            ],
            "context": {
                "source_count": 1,
                "source_labels": ["photosynthesis-basics.md"],
                "retrieval_evidence": True,
            },
            "answer": (
                "Photosynthesis converts light energy into chemical energy stored "
                "in glucose [1]. Practice next with two retrieval questions."
            ),
            "answer_status": "grounded",
            "citation_present": True,
        }
        assert contrast_step.status == "PASS"
        assert contrast_step.evidence is not None
        assert contrast_step.evidence["case_count"] == 3
        assert contrast_step.evidence["distinct_route_count"] == 3
        assert contrast_step.evidence["grounded_count"] == 1
        assert contrast_step.evidence["safe_abstention_count"] == 2
        assert [
            case["selected_tools"] for case in contrast_step.evidence["cases"]
        ] == [
            ["learner.get_profile", "rag.search", "quiz.generate"],
            ["cards.get_due"],
            ["rag.search"],
        ]
        assert reproducibility_step.status == "PASS"
        assert reproducibility_step.evidence is not None
        assert reproducibility_step.evidence["idempotency_replay"] == {
            "same_accepted_response": True,
            "same_result_projection": True,
        }
        assert len(reproducibility_step.evidence["evidence_payload_sha256"]) == 64
        assert set(reproducibility_step.evidence["case_projection_hashes"]) == {
            "grounded_success",
            "empty_cards",
            "prompt_injection",
        }
        assert fail_closed_step.status == "PASS"
        assert fail_closed_step.evidence is not None
        assert fail_closed_step.evidence["case_count"] == 6
        assert {
            case["error_code"] for case in fail_closed_step.evidence["cases"]
        } == {
            "idempotency_conflict",
            "validation_error",
            "payload_too_large",
            "unknown_tool",
            "forbidden_identity_args",
            "unknown_run",
        }
        assert process is not None
        assert process.poll() is None
    finally:
        if process is not None:
            acceptance._stop_process(process)


def test_acceptance_report_must_be_written_outside_checkout() -> None:
    output = acceptance.REPO_ROOT / "acceptance-report.json"

    assert acceptance.main(["--output", str(output)]) == 2
    assert not output.exists()


def test_command_timeout_fails_closed(monkeypatch) -> None:
    spec = acceptance.CommandSpec(
        "bounded",
        "Bounded command",
        ("python", "bounded.py"),
        timeout_sec=1.0,
    )

    def raise_timeout(*args, **kwargs):
        del args, kwargs
        raise subprocess.TimeoutExpired(spec.args, timeout=spec.timeout_sec)

    monkeypatch.setattr(acceptance.subprocess, "run", raise_timeout)

    result = acceptance._run_command(spec)

    assert result.status == "FAIL"
    assert result.summary == "timed out after 1 seconds"


def test_failed_report_does_not_claim_unexecuted_profiles_or_api() -> None:
    report = acceptance._build_report(
        metadata={"commit": "reviewed", "worktree_dirty": False},
        steps=[
            acceptance.StepResult(
                key="preflight",
                label="Environment preflight",
                status="PASS",
                duration_ms=1.0,
                summary="ok",
            ),
            acceptance.StepResult(
                key="contract_export",
                label="Exported contract integrity",
                status="FAIL",
                duration_ms=1.0,
                summary="failed",
            ),
        ],
        full_checks=False,
        port=acceptance.DEFAULT_PORT,
        overall_status="FAIL",
    )

    assert report["overall_status"] == "FAIL"
    assert report["profiles_executed"] == []
    assert report["api"]["smoke_status"] == "NOT_RUN"
    assert report["agentic_chain"] == {"status": "NOT_RUN"}
    assert report["contrastive_routing"] == {"status": "NOT_RUN"}
    assert report["reproducibility"] == {"status": "NOT_RUN"}
    assert report["fail_closed_http"] == {"status": "NOT_RUN"}
    assert report["evidence_payload_sha256"] is None


def test_static_answer_without_tool_context_chain_fails() -> None:
    step = acceptance._verify_agentic_chain(
        question="Explain photosynthesis.",
        completed={
            "state": "completed",
            "result": {
                "answer": "Photosynthesis is useful.",
                "answer_status": "grounded",
                "success": True,
                "sources": [],
                "steps": [],
                "trace": {},
            },
        },
        advertised_tools=[{"name": "rag.search"}],
    )

    assert step.status == "FAIL"
    assert "selected tool chain" in step.summary
    assert "retrieved context" in step.summary
    assert step.evidence is not None
    assert step.evidence["citation_present"] is False


def test_report_promotes_agentic_and_contrastive_evidence() -> None:
    evidence = {
        "question": "Question",
        "selected_tools": ["rag.search"],
        "context": {"source_count": 1},
        "answer": "Answer [1]",
        "answer_status": "grounded",
        "citation_present": True,
    }
    contrast_evidence = {
        "case_count": 3,
        "distinct_route_count": 3,
        "grounded_count": 1,
        "safe_abstention_count": 2,
        "cases": [],
    }
    reproducibility_evidence = {
        "case_projection_hashes": {"grounded_success": "a" * 64},
        "idempotency_replay": {
            "same_accepted_response": True,
            "same_result_projection": True,
        },
        "tool_args": [],
        "evidence_payload_sha256": "b" * 64,
    }
    fail_closed_evidence = {"case_count": 1, "cases": []}
    report = acceptance._build_report(
        metadata={"commit": "reviewed", "worktree_dirty": False},
        steps=[
            acceptance.StepResult(
                key="agentic_chain",
                label="Agentic execution chain",
                status="PASS",
                duration_ms=1.0,
                summary="verified",
                evidence=evidence,
            ),
            acceptance.StepResult(
                key="contrastive_routing",
                label="Contrastive routing and abstention",
                status="PASS",
                duration_ms=1.0,
                summary="verified",
                evidence=contrast_evidence,
            ),
            acceptance.StepResult(
                key="reproducibility",
                label="Reproducibility and tool arguments",
                status="PASS",
                duration_ms=1.0,
                summary="verified",
                evidence=reproducibility_evidence,
            ),
            acceptance.StepResult(
                key="fail_closed_http",
                label="Fail-closed HTTP safety",
                status="PASS",
                duration_ms=1.0,
                summary="verified",
                evidence=fail_closed_evidence,
            ),
        ],
        full_checks=False,
        port=acceptance.DEFAULT_PORT,
        overall_status="PASS",
    )

    assert report["schema_version"] == "agent-coach-acceptance-demo/1.3.0"
    assert report["agentic_chain"] == {"status": "PASS", **evidence}
    assert report["contrastive_routing"] == {
        "status": "PASS",
        **contrast_evidence,
    }
    assert report["reproducibility"] == {
        "status": "PASS",
        **reproducibility_evidence,
    }
    assert report["fail_closed_http"] == {"status": "PASS", **fail_closed_evidence}
    assert report["evidence_payload_sha256"] == "b" * 64
    assert report["steps"][0]["evidence"] == evidence
    assert report["steps"][1]["evidence"] == contrast_evidence


def test_contrastive_gate_rejects_identical_routes() -> None:
    repeated_result = {
        "state": "completed",
        "result": {
            "answer": (
                "I cannot provide a grounded answer from the available safe context."
            ),
            "answer_status": "abstain",
            "success": False,
            "sources": [],
            "steps": [{"tool_name": "rag.search", "tool_ok": True}],
            "trace": {
                "tool_calls": ["rag.search"],
                "grounding": {
                    "has_retrieval_evidence": False,
                    "has_source_citation": False,
                },
            },
        },
    }
    completed_cases = [
        acceptance.CompletedDemoCase(
            spec=spec,
            accepted={"polling_url": f"/v1/runs/{spec.scenario_id}"},
            completed={**repeated_result, "scenario_id": spec.scenario_id},
        )
        for spec in acceptance.CONTRAST_CASES
    ]

    step = acceptance._verify_contrastive_routing(
        completed_cases=completed_cases,
        advertised_tools=[{"name": "rag.search"}],
    )

    assert step.status == "FAIL"
    assert step.evidence is not None
    assert step.evidence["distinct_route_count"] == 1


def test_evidence_hash_is_stable_and_sensitive_to_projection_changes() -> None:
    projection = {
        "scenario_id": "grounded_success",
        "selected_tools": ["rag.search"],
    }

    first = acceptance._sha256_json(projection)
    second = acceptance._sha256_json(
        {"selected_tools": ["rag.search"], "scenario_id": "grounded_success"}
    )
    changed = acceptance._sha256_json(
        {"scenario_id": "grounded_success", "selected_tools": ["cards.get_due"]}
    )

    assert first == second
    assert first != changed
    assert len(first) == 64


def test_tool_arg_contract_rejects_forbidden_identity_args() -> None:
    failures = acceptance._tool_arg_contract_failures(
        scenario_id="grounded_success",
        question="Explain photosynthesis and suggest practice.",
        tool_name="rag.search",
        tool_args={"query": "photosynthesis energy glucose", "run_id": "attacker"},
        advertised_specs={
            "rag.search": {
                "args_schema": {
                    "properties": {"query": {}, "top_k": {}},
                    "required": ["query"],
                }
            }
        },
    )

    assert any("harness identity" in failure for failure in failures)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((acceptance.DEFAULT_HOST, 0))
        return int(server.getsockname()[1])
