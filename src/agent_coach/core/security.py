"""Default fail-closed security helpers for the standalone core."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import PureWindowsPath
from typing import Any

from agent_coach.core.contracts import ToolResult, ToolSpec

HARNESS_ONLY_FIELDS = frozenset(
    {"query_options", "question", "run_id", "session_id", "user_id"}
)
FORBIDDEN_MODEL_ARG_FIELDS = HARNESS_ONLY_FIELDS | {"scopes"}
DEFAULT_FALLBACK_ANSWER = (
    "I cannot provide a grounded answer from the available safe context."
)
MAX_TRACE_TEXT_CHARS = 300
RESERVED_TOOL_META_FIELDS = frozenset({"has_evidence", "sources"})
UNSAFE_TOOL_TEXT = "[REDACTED_UNSAFE_TOOL_TEXT]"

_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_SECRET_PATTERN = re.compile(
    r"\b(?:api[_ -]?key|token|secret|password)\b\s*[:=]?\s*([A-Za-z0-9_.+/=-]{6,})",
    re.IGNORECASE,
)
_INJECTION_PATTERN = re.compile(
    r"\b(ignore previous|system prompt|developer message|reveal.*secret)\b",
    re.IGNORECASE,
)
_PUBLIC_URL_PATTERN = r"https?://[^\s'\"<>|]+"
_PRIVATE_PATH_PATTERN = (
    r"(?:file:///[^\s'\"<>|]+)"
    r"|(?:[A-Za-z]:[\\/][^\s'\"<>|]+)"
    r"|(?:\\\\[^\\/\s'\"<>|]+\\[^\s'\"<>|]+)"
    r"|(?:(?<![:/])/(?!/)[^\s'\"<>|]+)"
)
_PATH_OR_URL_PATTERN = re.compile(
    rf"(?P<url>{_PUBLIC_URL_PATTERN})|(?P<path>{_PRIVATE_PATH_PATTERN})",
    re.IGNORECASE,
)
_PLACEHOLDER_PATTERN = re.compile(r"\[REDACTED_[A-Z_]+\]")
_SECRET_LABEL_PATTERN = re.compile(
    r"\b(?:api[_ -]?key|token|secret|password)\b\s*[:=]?",
    re.IGNORECASE,
)
_MEANINGFUL_WORD_PATTERN = re.compile(r"[A-Za-zА-Яа-я]{3,}")


def redact_sensitive_text(value: object) -> str:
    """Redact common credentials and direct identifiers from text."""

    text = str(value)
    text = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_PATTERN.sub("[REDACTED_PHONE]", text)
    text = _BEARER_PATTERN.sub("[REDACTED_BEARER]", text)
    return _SECRET_PATTERN.sub(
        lambda match: match.group(0).replace(match.group(1), "[REDACTED_SECRET]"),
        text,
    )


def _contains_forbidden_field(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_MODEL_ARG_FIELDS:
                return key_text
            nested = _contains_forbidden_field(item)
            if nested:
                return nested
    if isinstance(value, list):
        for item in value:
            nested = _contains_forbidden_field(item)
            if nested:
                return nested
    return None


def _schema_keys(schema: Mapping[str, object]) -> set[str]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return set()
    return {str(key) for key in properties}


def validate_tool_args_against_contract(
    tool: ToolSpec, args: Mapping[str, object]
) -> None:
    """Validate model-supplied args against core security contract invariants."""

    forbidden = _contains_forbidden_field(args)
    if forbidden:
        raise ValueError(f"planner supplied forbidden field: {forbidden}")
    if not isinstance(args, Mapping):
        raise ValueError("tool args must be an object")
    _validate_json_schema_value(tool.args_schema, args, path="args")


def _validate_json_schema_value(
    schema: Mapping[str, Any],
    value: object,
    *,
    path: str,
    root_schema: Mapping[str, Any] | None = None,
) -> None:
    root = schema if root_schema is None else root_schema
    ref = schema.get("$ref")
    if isinstance(ref, str):
        schema = _resolve_local_ref(root, ref)
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        errors: list[str] = []
        for option in any_of:
            if not isinstance(option, Mapping):
                continue
            try:
                _validate_json_schema_value(
                    option, value, path=path, root_schema=root
                )
            except ValueError as exc:
                errors.append(str(exc))
            else:
                return
        message = f"{path} did not match any allowed schema: {'; '.join(errors)}"
        raise ValueError(message)

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        raise ValueError(f"{path} must be one of {enum_values!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        _validate_json_type(str(expected_type), value, path=path)

    if isinstance(value, str):
        _validate_string_constraints(schema, value, path=path)
    if isinstance(value, int | float) and not isinstance(value, bool):
        _validate_number_constraints(schema, value, path=path)
    if isinstance(value, list):
        _validate_array_constraints(schema, value, path=path, root_schema=root)
    if isinstance(value, Mapping):
        _validate_object_constraints(schema, value, path=path, root_schema=root)


def _validate_json_type(expected_type: str, value: object, *, path: str) -> None:
    validators = {
        "array": lambda item: isinstance(item, list),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "null": lambda item: item is None,
        "number": lambda item: isinstance(item, int | float)
        and not isinstance(item, bool),
        "object": lambda item: isinstance(item, Mapping),
        "string": lambda item: isinstance(item, str),
    }
    validator = validators.get(expected_type)
    if validator is None:
        raise ValueError(f"unsupported schema type at {path}: {expected_type}")
    if not validator(value):
        raise ValueError(f"{path} must be {expected_type}")


def _validate_string_constraints(
    schema: Mapping[str, Any], value: str, *, path: str
) -> None:
    min_length = schema.get("minLength")
    max_length = schema.get("maxLength")
    if isinstance(min_length, int) and len(value) < min_length:
        raise ValueError(f"{path} is shorter than minLength={min_length}")
    if isinstance(max_length, int) and len(value) > max_length:
        raise ValueError(f"{path} is longer than maxLength={max_length}")


def _validate_number_constraints(
    schema: Mapping[str, Any], value: int | float, *, path: str
) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(minimum, int | float) and value < minimum:
        raise ValueError(f"{path} is less than minimum={minimum}")
    if isinstance(maximum, int | float) and value > maximum:
        raise ValueError(f"{path} is greater than maximum={maximum}")


def _validate_array_constraints(
    schema: Mapping[str, Any],
    value: list[object],
    *,
    path: str,
    root_schema: Mapping[str, Any],
) -> None:
    min_items = schema.get("minItems")
    max_items = schema.get("maxItems")
    if isinstance(min_items, int) and len(value) < min_items:
        raise ValueError(f"{path} has fewer than minItems={min_items}")
    if isinstance(max_items, int) and len(value) > max_items:
        raise ValueError(f"{path} has more than maxItems={max_items}")
    item_schema = schema.get("items")
    if isinstance(item_schema, Mapping):
        for index, item in enumerate(value):
            _validate_json_schema_value(
                item_schema, item, path=f"{path}[{index}]", root_schema=root_schema
            )


def _validate_object_constraints(
    schema: Mapping[str, Any],
    value: Mapping[str, object],
    *,
    path: str,
    root_schema: Mapping[str, Any],
) -> None:
    if schema.get("additionalProperties") is False:
        allowed = _schema_keys(schema)
        extra = sorted(str(key) for key in value if str(key) not in allowed)
        if extra:
            raise ValueError(f"unexpected field(s) at {path}: {', '.join(extra)}")
    required = schema.get("required")
    if isinstance(required, list):
        missing = sorted(str(key) for key in required if key not in value)
        if missing:
            message = f"missing required field(s) at {path}: {', '.join(missing)}"
            raise ValueError(message)
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for key, property_schema in properties.items():
            if key in value and isinstance(property_schema, Mapping):
                _validate_json_schema_value(
                    property_schema,
                    value[key],
                    path=f"{path}.{key}",
                    root_schema=root_schema,
                )


def _resolve_local_ref(root_schema: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise ValueError(f"unsupported schema ref: {ref}")
    defs = root_schema.get("$defs")
    name = ref.removeprefix(prefix)
    if not isinstance(defs, Mapping) or not isinstance(defs.get(name), Mapping):
        raise ValueError(f"unresolved schema ref: {ref}")
    return defs[name]


def _redact_value(value: object, *, max_chars: int) -> object:
    if isinstance(value, str):
        redacted = _sanitize_projection_text(value)
        return redacted if len(redacted) <= max_chars else redacted[:max_chars]
    if isinstance(value, Mapping):
        return {
            sanitize_identifier(key, max_chars=max_chars): _redact_value(
                item, max_chars=max_chars
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, max_chars=max_chars) for item in value]
    return value


def trace_text(value: object, *, max_chars: int = MAX_TRACE_TEXT_CHARS) -> str:
    """Return redacted bounded text for public run projections."""

    redacted = _sanitize_projection_text(value)
    return redacted if len(redacted) <= max_chars else redacted[:max_chars]


def redacted_mapping(
    value: Mapping[str, object], *, max_chars: int = MAX_TRACE_TEXT_CHARS
) -> dict[str, object]:
    """Return a recursively redacted mapping safe for trace projections."""

    return {
        sanitize_identifier(key, max_chars=max_chars): _redact_value(
            item, max_chars=max_chars
        )
        for key, item in value.items()
    }


def sanitize_identifier(
    value: object, *, max_chars: int = MAX_TRACE_TEXT_CHARS
) -> str:
    """Return a redacted bounded identifier safe for public projections."""

    sanitized = trace_text(value, max_chars=max_chars)
    return sanitized or "[REDACTED_IDENTIFIER]"


def compact_tool_result(result: ToolResult, *, max_chars: int) -> ToolResult:
    """Project raw tool output to compact redacted trace-safe form."""

    meta = {
        sanitize_identifier(key, max_chars=160): _redact_value(value, max_chars=400)
        for key, value in result.meta.items()
        if key not in RESERVED_TOOL_META_FIELDS
    }
    raw_sources = result.meta.get("sources")
    has_evidence = _has_grounding_evidence(result.data, raw_sources)
    if isinstance(raw_sources, list):
        meta["sources"] = [_compact_source(source) for source in raw_sources]
    if has_evidence:
        meta["has_evidence"] = True
    summary = _result_summary(result.data)
    data = {"summary": trace_text(summary, max_chars=max_chars)} if summary else None
    error = (
        trace_text(result.error, max_chars=400) if result.error is not None else None
    )
    return ToolResult(ok=result.ok, data=data, error=error, meta=meta)


def _compact_source(source: object) -> dict[str, object]:
    if not isinstance(source, Mapping):
        return {"source": trace_text(source, max_chars=160)}
    allowed = (
        "cite_index",
        "file",
        "file_name",
        "index",
        "line_end",
        "line_start",
        "node_id",
        "page",
        "path",
        "relative_path",
        "source",
        "title",
        "url",
    )
    compact: dict[str, object] = {}
    for key in allowed:
        if key not in source or source[key] in (None, "", [], {}):
            continue
        value = source[key]
        if key in {"file", "path", "relative_path"} and isinstance(value, str):
            value = _public_path_label(value)
        compact[key] = _redact_value(value, max_chars=160)
    return compact


def _sanitize_projection_text(value: object) -> str:
    redacted = redact_sensitive_text(value)
    if _INJECTION_PATTERN.search(redacted):
        return UNSAFE_TOOL_TEXT
    return _replace_private_paths(redacted)


def _is_safe_evidence_text(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    redacted = redact_sensitive_text(value)
    if _INJECTION_PATTERN.search(redacted):
        return False
    sanitized = _sanitize_projection_text(value)
    if sanitized == UNSAFE_TOOL_TEXT:
        return False
    return _has_meaningful_projection_text(
        _strip_redacted_only_content(sanitized, original=value)
    )


def _has_meaningful_projection_text(value: str) -> bool:
    without_placeholders = _PLACEHOLDER_PATTERN.sub(" ", value)
    return bool(_MEANINGFUL_WORD_PATTERN.search(without_placeholders))


def _strip_redacted_only_content(value: str, *, original: str) -> str:
    stripped = _PLACEHOLDER_PATTERN.sub(" ", value)
    stripped = _SECRET_LABEL_PATTERN.sub(" ", stripped)
    for label in _private_path_labels(original):
        stripped = stripped.replace(label, " ")
    return stripped


def _replace_private_paths(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        public_url = match.group("url")
        if public_url is not None:
            return public_url
        return _public_path_label(match.group("path") or "")

    replaced = _PATH_OR_URL_PATTERN.sub(_replace, value)
    if _looks_private_or_absolute_path(replaced):
        return _public_path_label(replaced)
    return replaced


def _private_path_labels(value: str) -> list[str]:
    labels = [
        _public_path_label(path)
        for match in _PATH_OR_URL_PATTERN.finditer(value)
        if (path := match.group("path")) is not None
    ]
    if _looks_private_or_absolute_path(value):
        labels.append(_public_path_label(value))
    return labels


def _public_path_label(value: str) -> str:
    text = value.strip()
    if text.casefold().startswith(("http://", "https://")):
        return text
    if text.casefold().startswith("file://"):
        text = text[7:]
    if _looks_private_or_absolute_path(text):
        return PureWindowsPath(text.replace("/", "\\")).name or "[REDACTED_PATH]"
    return text


def _looks_private_or_absolute_path(value: str) -> bool:
    lowered = value.casefold()
    if lowered.startswith(("http://", "https://")):
        return False
    normalized = lowered.replace("/", "\\")
    return (
        bool(re.match(r"^[a-z]:[\\/]", value, flags=re.IGNORECASE))
        or lowered.startswith("file:///")
        or value.startswith("\\\\")
        or value.startswith(("/", "\\"))
        or "projects\\hometutor" in normalized
        or "users\\kostya" in normalized
    )


def _has_grounding_evidence(data: object, sources: object) -> bool:
    if isinstance(data, Mapping):
        chunks = data.get("chunks")
        if isinstance(chunks, list) and any(
            isinstance(chunk, Mapping)
            and _is_safe_evidence_text(chunk.get("text"))
            for chunk in chunks
        ):
            return True
        if _is_safe_evidence_text(data.get("answer")):
            return True
    if isinstance(sources, list):
        return any(
            isinstance(source, Mapping)
            and _is_safe_evidence_text(source.get("text"))
            for source in sources
        )
    return False


def _result_summary(data: object) -> str:
    if isinstance(data, Mapping):
        answer = data.get("answer")
        if _is_safe_evidence_text(answer):
            return "tool returned answer evidence"
        chunks = data.get("chunks")
        if isinstance(chunks, list):
            for chunk in chunks:
                if isinstance(chunk, Mapping):
                    text = chunk.get("text")
                    if _is_safe_evidence_text(text):
                        return "tool returned retrieval evidence"
        summary = data.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary
        return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(data, str):
        return data
    return ""


class DefaultSecurityPolicy:
    """Small package-owned policy used by local tests and composition roots."""

    def __init__(self, *, max_result_chars: int = 2000) -> None:
        self._max_result_chars = max_result_chars

    def validate_tool_args(self, tool: ToolSpec, args: Mapping[str, object]) -> None:
        validate_tool_args_against_contract(tool, args)

    def secure_tool_result(self, result: ToolResult) -> ToolResult:
        return compact_tool_result(result, max_chars=self._max_result_chars)

    def guard_final_answer(
        self, answer: str, sources: list[dict[str, object]]
    ) -> tuple[str, bool, bool, bool]:
        del sources
        redacted = _sanitize_projection_text(answer)
        was_redacted = redacted != answer
        if redacted == UNSAFE_TOOL_TEXT or _INJECTION_PATTERN.search(redacted):
            return (
                self.fallback_answer("suspicious_output", DEFAULT_FALLBACK_ANSWER),
                was_redacted,
                True,
                True,
            )
        return redacted, was_redacted, False, False

    def fallback_answer(self, code: str, default: str) -> str:
        del code
        return default
