"""Explicit model routing policy. Roles are not inferred from model id strings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_coach.core.contracts import AgentStep
from agent_coach.provider.config import (
    PLANNER_ROLE,
    SYNTHESIZER_ROLE,
    LiveProviderConfig,
)


@dataclass(frozen=True)
class RoutedModel:
    """One selected model role for the next provider call."""

    role: str
    model_id: str
    backend: str
    routing_status: str


class ModelRouter:
    """Route planner vs synthesizer from observed tool success, not model names."""

    def __init__(self, config: LiveProviderConfig) -> None:
        self._config = config

    @property
    def routing_status(self) -> str:
        return self._config.routing_status

    def select_role(self, steps: Sequence[AgentStep]) -> str:
        if any(
            step.tool_result is not None and step.tool_result.ok for step in steps
        ):
            return SYNTHESIZER_ROLE
        return PLANNER_ROLE

    def route(self, steps: Sequence[AgentStep]) -> RoutedModel:
        role = self.select_role(steps)
        settings = self._config.settings_for(role)
        return RoutedModel(
            role=role,
            model_id=settings.model_id,
            backend=settings.backend,
            routing_status=self.routing_status,
        )
