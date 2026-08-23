"""Synthetic public fixtures for deterministic mock adapter runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

MOCK_FIXTURE_SCHEMA_VERSION = "agent-coach-mock-fixtures/1.0.0"
DEFAULT_FIXTURE_RESOURCE = "mock_scenarios.json"


@dataclass(frozen=True)
class MockScenario:
    """One deterministic planner/tool script."""

    scenario_id: str
    question: str
    run_id: str
    decisions: tuple[dict[str, Any], ...]
    tool_results: tuple[dict[str, Any], ...]
    expected: dict[str, Any]


@dataclass(frozen=True)
class MockFixture:
    """Loaded fixture bundle."""

    schema_version: str
    provenance: dict[str, Any]
    advertised_read_only_tools: tuple[str, ...]
    controlled_outcomes: tuple[str, ...]
    scenarios: dict[str, MockScenario]


def load_mock_fixture(path: Path | None = None) -> MockFixture:
    """Load and validate the package-owned synthetic mock fixture bundle."""

    raw_text = (
        resources.files("agent_coach.data")
        .joinpath(DEFAULT_FIXTURE_RESOURCE)
        .read_text(encoding="utf-8")
        if path is None
        else path.read_text(encoding="utf-8")
    )
    raw = json.loads(raw_text)
    schema_version = str(raw.get("schema_version") or "")
    if schema_version != MOCK_FIXTURE_SCHEMA_VERSION:
        raise ValueError("unsupported mock fixture schema version")
    tools = tuple(str(name) for name in raw.get("advertised_read_only_tools") or ())
    outcomes = tuple(str(name) for name in raw.get("controlled_outcomes") or ())
    if not tools:
        raise ValueError("mock fixture must advertise at least one read-only tool")
    if not outcomes:
        raise ValueError("mock fixture must declare controlled outcomes")
    scenarios: dict[str, MockScenario] = {}
    for item in raw.get("scenarios") or ():
        if not isinstance(item, dict):
            raise ValueError("mock scenarios must be objects")
        scenario_id = str(item.get("id") or "")
        if not scenario_id:
            raise ValueError("mock scenario id is required")
        if scenario_id in scenarios:
            raise ValueError(f"duplicate mock scenario id: {scenario_id}")
        scenarios[scenario_id] = MockScenario(
            scenario_id=scenario_id,
            question=str(item.get("question") or ""),
            run_id=str(item.get("run_id") or scenario_id),
            decisions=tuple(dict(decision) for decision in item.get("decisions") or ()),
            tool_results=tuple(
                dict(result) for result in item.get("tool_results") or ()
            ),
            expected=dict(item.get("expected") or {}),
        )
    if not scenarios:
        raise ValueError("mock fixture must contain scenarios")
    return MockFixture(
        schema_version=schema_version,
        provenance=dict(raw.get("provenance") or {}),
        advertised_read_only_tools=tools,
        controlled_outcomes=outcomes,
        scenarios=scenarios,
    )
