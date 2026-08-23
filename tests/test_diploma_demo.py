from __future__ import annotations

import json

from scripts.run_diploma_demo import main


def test_diploma_demo_writes_reproducible_public_evidence(tmp_path, capsys) -> None:
    output = tmp_path / "diploma_demo.json"

    assert main(["--output", str(output)]) == 0

    stdout = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == stdout
    assert written["schema_version"] == "agent-coach-diploma-evidence/1.0.0"
    assert written["repository"] == "agent-coach"
    assert written["adapter_profile"] == "mock"
    assert written["scenario_id"] == "grounded_success"
    assert written["mock_api"]["production_auth"] is False
    assert written["mock_api"]["state_store"] == "ephemeral_in_memory"
    assert written["result"]["answer_status"] == "grounded"
    assert written["result"]["success"] is True
    assert written["result"]["tool_call_count"] == 3
    assert written["result"]["tool_calls"] == [
        "learner.get_profile",
        "rag.search",
        "quiz.generate",
    ]
    assert written["store_events"] == [
        "started",
        "step",
        "step",
        "step",
        "step",
        "completed",
    ]
    serialized = json.dumps(written, sort_keys=True)
    assert "\\".join(("D:", "Projects", "hometutor")) not in serialized
    assert "\\".join(("C:", "Users", "Kostya")) not in serialized


def test_diploma_demo_rejects_unknown_scenario(capsys) -> None:
    assert main(["--scenario", "missing"]) == 2

    assert "unknown mock scenario" in capsys.readouterr().out
