from __future__ import annotations

import json
from pathlib import Path

from agent_coach.retrieval import RetrievalConfig, build_local_vector_index

DISCOVERY_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "eval_discovery"
    / "d11_eval_v2_discovery.json"
)
CURRENT_DENYLIST_LITERALS = (
    "ignore previous",
    "system prompt",
    "developer message",
)


def _discovery() -> dict[str, object]:
    return json.loads(DISCOVERY_PATH.read_text(encoding="utf-8"))


def test_d11_eval_v2_discovery_freezes_exact_registry_shape() -> None:
    payload = _discovery()
    cases = payload["proposed_new_cases"]

    assert payload["current_case_count"] == 27
    assert payload["proposed_suite_version"] == "2.0.0"
    assert payload["proposed_final_case_count"] == 47
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["duplicate_of_existing_case"] for case in cases} == {False}
    assert all(case["denominator"] for case in cases)
    assert "EXPECTED_CASE_COUNT" in payload["mechanical_locks"]
    assert "EXPECTED_CASE_IDS" in payload["mechanical_locks"]
    assert "case_count_not_27" in payload["mechanical_locks"]


def test_d11_eval_v2_discovery_retrieval_cases_match_frozen_corpus() -> None:
    payload = _discovery()
    cases = payload["proposed_new_cases"]
    config = RetrievalConfig()
    store, knowledge_base = build_local_vector_index(config=config)
    negatives = set(knowledge_base.declared_negative_queries)
    band_low, band_high = payload["near_threshold_score_band"]

    for case in cases:
        if case["type"] == "retrieval_negative":
            assert case["input"] in negatives
            hits = store.search(
                case["input"],
                top_k=1,
                threshold=config.score_threshold,
            )
            assert hits == ()
        if case["category"] == "retrieval_boundary":
            hits = store.search(case["input"], top_k=1, threshold=0.0)
            assert hits
            assert hits[0].chunk.chunk_id == case["expected_chunk_id"]
            assert band_low <= hits[0].score <= band_high


def test_d11_eval_v2_discovery_security_inputs_do_not_duplicate_denylist() -> None:
    payload = _discovery()

    for case in payload["proposed_new_cases"]:
        if case["category"] != "prompt_injection":
            continue
        lowered = case["input"].lower()
        assert "reveal" not in lowered or "secret" not in lowered
        for literal in CURRENT_DENYLIST_LITERALS:
            assert literal not in lowered


def test_d11_eval_v2_discovery_max_cost_uses_positive_offline_estimate() -> None:
    payload = _discovery()
    max_cost = next(case for case in payload["proposed_new_cases"]
                    if case["id"] == "budget-max-cost")

    assert max_cost["type"] == "core_max_cost"
    assert "estimated_cost_usd=0.02" in max_cost["input"]
    assert max_cost["expected_terminal_state"] == "stopped/max_cost"
