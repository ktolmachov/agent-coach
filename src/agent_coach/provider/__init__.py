"""Optional live-provider adapters. Core does not import this package."""

from agent_coach.provider.config import (
    DEFAULT_PLANNER_MODEL_ID,
    DEFAULT_SYNTHESIZER_MODEL_ID,
    LiveProviderConfig,
    ModelRoleSettings,
    load_live_provider_config,
)
from agent_coach.provider.errors import LiveConfigurationError, ProviderAdapterError
from agent_coach.provider.model_router import (
    PLANNER_ROLE,
    SYNTHESIZER_ROLE,
    ModelRouter,
    RoutedModel,
)
from agent_coach.provider.openai_responses import (
    NormalizedFunctionCall,
    NormalizedResponse,
    OpenAIResponsesPlanner,
    PlannerToolRequirement,
    ProviderRequest,
    ScriptedResponsesClient,
    build_official_responses_client,
)
from agent_coach.provider.tool_schema import tool_specs_to_openai_tools

__all__ = [
    "DEFAULT_PLANNER_MODEL_ID",
    "DEFAULT_SYNTHESIZER_MODEL_ID",
    "LiveConfigurationError",
    "LiveProviderConfig",
    "ModelRoleSettings",
    "ModelRouter",
    "NormalizedFunctionCall",
    "NormalizedResponse",
    "OpenAIResponsesPlanner",
    "PLANNER_ROLE",
    "PlannerToolRequirement",
    "ProviderAdapterError",
    "ProviderRequest",
    "RoutedModel",
    "SYNTHESIZER_ROLE",
    "ScriptedResponsesClient",
    "build_official_responses_client",
    "load_live_provider_config",
    "tool_specs_to_openai_tools",
]
