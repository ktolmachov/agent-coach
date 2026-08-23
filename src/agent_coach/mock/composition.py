"""Composition root for deterministic offline mock runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from agent_coach.core import AgentRunner, RunLimits, RunRequest, ToolAccess, ToolSpec
from agent_coach.core.contracts import tool_specs_from_contract_bundle
from agent_coach.mock.adapters import (
    DeterministicClock,
    DeterministicPlanner,
    EphemeralRunStore,
    MockSecurityPolicy,
    MockToolAdapter,
)
from agent_coach.mock.fixtures import MockFixture, MockScenario, load_mock_fixture

DEFAULT_CONTRACT_BUNDLE_RESOURCE = "agent_contract_bundle.json"


@dataclass(frozen=True)
class MockComposition:
    """Fully wired deterministic runner and its public inputs."""

    runner: AgentRunner
    request: RunRequest
    store: EphemeralRunStore
    scenario: MockScenario
    tools: tuple[ToolSpec, ...]


def advertised_mock_tools(
    fixture: MockFixture | None = None,
    *,
    contract_bundle_path: Path | None = None,
) -> tuple[ToolSpec, ...]:
    """Return the predeclared read-only mock subset from the frozen D2 bundle."""

    loaded_fixture = load_mock_fixture() if fixture is None else fixture
    bundle_text = (
        resources.files("agent_coach.data")
        .joinpath(DEFAULT_CONTRACT_BUNDLE_RESOURCE)
        .read_text(encoding="utf-8")
        if contract_bundle_path is None
        else contract_bundle_path.read_text(encoding="utf-8")
    )
    bundle = json.loads(bundle_text)
    read_only_tools = tool_specs_from_contract_bundle(bundle)
    by_name = {tool.name: tool for tool in read_only_tools}
    selected: list[ToolSpec] = []
    for name in loaded_fixture.advertised_read_only_tools:
        tool = by_name.get(name)
        if tool is None:
            raise ValueError(f"mock tool is absent from read-only contract: {name}")
        if tool.access is not ToolAccess.READ:
            raise ValueError(f"mock tool is not read-only: {name}")
        selected.append(tool)
    return tuple(selected)


def build_mock_composition(
    scenario_id: str,
    *,
    fixture: MockFixture | None = None,
    contract_bundle_path: Path | None = None,
) -> MockComposition:
    """Build a deterministic offline Agent Core composition for one scenario."""

    loaded_fixture = load_mock_fixture() if fixture is None else fixture
    try:
        scenario = loaded_fixture.scenarios[scenario_id]
    except KeyError as exc:
        raise ValueError(f"unknown mock scenario: {scenario_id}") from exc
    tools = advertised_mock_tools(
        loaded_fixture,
        contract_bundle_path=contract_bundle_path,
    )
    store = EphemeralRunStore()
    runner = AgentRunner(
        planner=DeterministicPlanner(scenario),
        tools=tools,
        tool_executor=MockToolAdapter(scenario),
        security_policy=MockSecurityPolicy(),
        clock=DeterministicClock(),
        run_store=store,
    )
    request = RunRequest(
        question=scenario.question,
        user_id="demo-user",
        session_id="demo-session",
        run_id=scenario.run_id,
        query_options={"adapter_profile": "mock", "scenario_id": scenario_id},
        limits=RunLimits(max_steps=6, tool_error_limit=3),
    )
    return MockComposition(
        runner=runner,
        request=request,
        store=store,
        scenario=scenario,
        tools=tools,
    )
