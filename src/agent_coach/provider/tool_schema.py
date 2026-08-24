"""Convert frozen ToolSpec contracts into OpenAI Responses function tools."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from agent_coach.core.contracts import ToolAccess, ToolSpec

PROVIDER_FUNCTION_TYPE = "function"
PROVIDER_TOOL_CHOICE_AUTO = "auto"


def tool_specs_to_openai_tools(
    tools: Sequence[ToolSpec],
) -> list[dict[str, Any]]:
    """Return native Responses function tools. Write tools are rejected."""

    converted: list[dict[str, Any]] = []
    for tool in tools:
        if tool.access is not ToolAccess.READ:
            raise ValueError(
                f"write tools are not advertised to the provider: {tool.name}"
            )
        description = " ".join(
            part for part in (tool.description, tool.when_to_use) if part
        ).strip()
        converted.append(
            {
                "type": PROVIDER_FUNCTION_TYPE,
                "name": tool.name,
                "description": description,
                "parameters": _parameters_schema(tool.args_schema),
                "strict": False,
            }
        )
    return converted


def _parameters_schema(args_schema: dict[str, Any]) -> dict[str, Any]:
    schema = (
        deepcopy(args_schema)
        if args_schema
        else {"type": "object", "properties": {}}
    )
    if not isinstance(schema, dict):
        raise ValueError("tool args_schema must be an object")
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.setdefault("additionalProperties", False)
    return schema
