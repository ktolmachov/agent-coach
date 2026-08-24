"""Trusted live-provider settings. Environment reads stay in this module."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import unquote, urlsplit, urlunsplit

from agent_coach.provider.errors import LiveConfigurationError

DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_PLANNER_MODEL_ID = "gpt-4.1-mini"
DEFAULT_SYNTHESIZER_MODEL_ID = "gpt-4.1"
DEFAULT_BACKEND = "openai_responses"
PLANNER_ROLE = "planner"
SYNTHESIZER_ROLE = "synthesizer"
EMBEDDING_ROLE = "embedding"
ROUTING_DISTINCT = "distinct_models"
ROUTING_DEGRADED = "degraded_same_model"

_ENV_API_KEY = "AGENT_COACH_LIVE_API_KEY"
_ENV_API_BASE = "AGENT_COACH_LIVE_API_BASE"
_ENV_PLANNER_MODEL = "AGENT_COACH_PLANNER_MODEL"
_ENV_SYNTHESIZER_MODEL = "AGENT_COACH_SYNTHESIZER_MODEL"
_ENV_EMBEDDING_MODEL = "AGENT_COACH_EMBEDDING_MODEL"
_ENV_TIMEOUT = "AGENT_COACH_LIVE_TIMEOUT_SEC"
_ENV_RETRIES = "AGENT_COACH_LIVE_MAX_RETRIES"
_ENV_MAX_OUTPUT = "AGENT_COACH_LIVE_MAX_OUTPUT_TOKENS"
_ENV_COST_CAP = "AGENT_COACH_LIVE_COST_CAP_USD"
_ENV_MAX_QUESTION_CHARS = "AGENT_COACH_LIVE_MAX_QUESTION_CHARS"
_ENV_MAX_RUN_TOKENS = "AGENT_COACH_LIVE_MAX_RUN_TOKENS"
_ENV_RUN_TIME_LIMIT = "AGENT_COACH_LIVE_RUN_TIME_LIMIT_SEC"

_PUBLIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SECRETISH_PATTERN = re.compile(
    r"(api[_-]?key|bearer|password|secret|token|sk-[A-Za-z0-9])",
    re.IGNORECASE,
)
_REDACTED_ID = "[REDACTED_IDENTIFIER]"


@dataclass(frozen=True)
class ModelRoleSettings:
    """One configured model role."""

    role: str
    model_id: str
    backend: str = DEFAULT_BACKEND

    def __post_init__(self) -> None:
        role = _safe_public_id(self.role, field_name="model role")
        backend = _safe_public_id(self.backend, field_name="model backend")
        model_id = _safe_public_id(self.model_id, field_name="model id")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "backend", backend)

    def safe_projection(self) -> dict[str, str]:
        return {
            "role": self.role,
            "model_id": _public_config_id(self.model_id),
            "backend": self.backend,
        }


@dataclass(frozen=True)
class LiveProviderConfig:
    """Trusted live settings. The API key is never part of the public projection."""

    api_key: str = field(repr=False)
    api_base: str = DEFAULT_API_BASE
    planner: ModelRoleSettings = field(
        default_factory=lambda: ModelRoleSettings(
            role=PLANNER_ROLE, model_id=DEFAULT_PLANNER_MODEL_ID
        )
    )
    synthesizer: ModelRoleSettings = field(
        default_factory=lambda: ModelRoleSettings(
            role=SYNTHESIZER_ROLE, model_id=DEFAULT_SYNTHESIZER_MODEL_ID
        )
    )
    embedding: ModelRoleSettings | None = None
    timeout_sec: float = 30.0
    max_retries: int = 0
    max_output_tokens: int = 400
    cost_cap_usd: float = 0.0
    max_question_chars: int = 2000
    max_run_tokens: int = 4000
    run_time_limit_sec: float = 60.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "api_base", _safe_api_base(self.api_base))
        _require_positive_number(self.timeout_sec, "timeout_sec")
        _require_nonnegative_int_value(self.max_retries, "max_retries")
        _require_positive_int_value(self.max_output_tokens, "max_output_tokens")
        _require_nonnegative_number(self.cost_cap_usd, "cost_cap_usd")
        _require_positive_int_value(self.max_question_chars, "max_question_chars")
        _require_positive_int_value(self.max_run_tokens, "max_run_tokens")
        _require_positive_number(self.run_time_limit_sec, "run_time_limit_sec")

    def __repr__(self) -> str:
        return (
            "LiveProviderConfig("
            f"api_base={_public_api_base(self.api_base)!r}, "
            f"planner_model={_public_config_id(self.planner.model_id)!r}, "
            f"synthesizer_model={_public_config_id(self.synthesizer.model_id)!r}, "
            "api_key=***"
            ")"
        )

    def __str__(self) -> str:
        return self.__repr__()

    @property
    def routing_status(self) -> str:
        if self.planner.model_id == self.synthesizer.model_id:
            return ROUTING_DEGRADED
        return ROUTING_DISTINCT

    def settings_for(self, role: str) -> ModelRoleSettings:
        if role == PLANNER_ROLE:
            return self.planner
        if role == SYNTHESIZER_ROLE:
            return self.synthesizer
        if role == EMBEDDING_ROLE and self.embedding is not None:
            return self.embedding
        raise LiveConfigurationError(
            "invalid_config",
            f"unknown model role {role!r}",
        )

    def safe_projection(self) -> dict[str, object]:
        projection: dict[str, object] = {
            "api_base": _public_api_base(self.api_base),
            "planner": self.planner.safe_projection(),
            "synthesizer": self.synthesizer.safe_projection(),
            "timeout_sec": self.timeout_sec,
            "max_retries": self.max_retries,
            "max_output_tokens": self.max_output_tokens,
            "cost_cap_usd": self.cost_cap_usd,
            "max_question_chars": self.max_question_chars,
            "max_run_tokens": self.max_run_tokens,
            "run_time_limit_sec": self.run_time_limit_sec,
            "routing_status": self.routing_status,
            "backend": DEFAULT_BACKEND,
        }
        if self.embedding is not None:
            projection["embedding"] = self.embedding.safe_projection()
        return projection


def load_live_provider_config(
    environ: Mapping[str, str] | None = None,
    *,
    require_api_key: bool = True,
) -> LiveProviderConfig:
    """Load live settings from an explicit mapping or process environment."""

    env = _environ(environ)
    api_key = (env.get(_ENV_API_KEY) or "").strip()
    if require_api_key and not api_key:
        raise LiveConfigurationError(
            "missing_api_key",
            "live profile requires AGENT_COACH_LIVE_API_KEY",
        )
    planner_id = (env.get(_ENV_PLANNER_MODEL) or DEFAULT_PLANNER_MODEL_ID).strip()
    synthesizer_id = (
        env.get(_ENV_SYNTHESIZER_MODEL) or DEFAULT_SYNTHESIZER_MODEL_ID
    ).strip()
    embedding_id = (env.get(_ENV_EMBEDDING_MODEL) or "").strip()
    api_base = (env.get(_ENV_API_BASE) or DEFAULT_API_BASE).strip() or DEFAULT_API_BASE
    embedding = None
    if embedding_id:
        embedding = ModelRoleSettings(role=EMBEDDING_ROLE, model_id=embedding_id)
    return LiveProviderConfig(
        api_key=api_key,
        api_base=_safe_api_base(api_base),
        planner=ModelRoleSettings(role=PLANNER_ROLE, model_id=planner_id),
        synthesizer=ModelRoleSettings(role=SYNTHESIZER_ROLE, model_id=synthesizer_id),
        embedding=embedding,
        timeout_sec=_positive_float(env.get(_ENV_TIMEOUT), 30.0, _ENV_TIMEOUT),
        max_retries=_nonnegative_int(env.get(_ENV_RETRIES), 0, _ENV_RETRIES),
        max_output_tokens=_positive_int(env.get(_ENV_MAX_OUTPUT), 400, _ENV_MAX_OUTPUT),
        cost_cap_usd=_nonnegative_float(env.get(_ENV_COST_CAP), 0.0, _ENV_COST_CAP),
        max_question_chars=_positive_int(
            env.get(_ENV_MAX_QUESTION_CHARS), 2000, _ENV_MAX_QUESTION_CHARS
        ),
        max_run_tokens=_positive_int(
            env.get(_ENV_MAX_RUN_TOKENS), 4000, _ENV_MAX_RUN_TOKENS
        ),
        run_time_limit_sec=_positive_float(
            env.get(_ENV_RUN_TIME_LIMIT), 60.0, _ENV_RUN_TIME_LIMIT
        ),
    )


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    if environ is not None:
        return environ
    import os

    return os.environ


def _safe_api_base(value: str) -> str:
    stripped = value.strip()
    parsed = urlsplit(stripped)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise LiveConfigurationError("invalid_config", "live API base is invalid")
    if parsed.scheme == "http" and not _is_loopback_api_host(parsed.hostname or ""):
        raise LiveConfigurationError(
            "invalid_config",
            "live API base must use HTTPS except for loopback hosts",
        )
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise LiveConfigurationError(
            "invalid_config",
            "live API base must not embed credentials",
        )
    if parsed.query or parsed.fragment:
        raise LiveConfigurationError(
            "invalid_config",
            "live API base must not include query or fragment",
        )
    decoded_host = _decode_api_base_host(parsed.hostname or "")
    if _SECRETISH_PATTERN.search(decoded_host):
        raise LiveConfigurationError(
            "invalid_config",
            "live API base host must not contain secrets",
        )
    path = parsed.path.rstrip("/")
    decoded_path = _decode_api_base_path(path)
    if _SECRETISH_PATTERN.search(decoded_path):
        raise LiveConfigurationError(
            "invalid_config",
            "live API base path must not contain secrets",
        )
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _decode_api_base_host(host: str) -> str:
    decoded = unquote(host)
    if unquote(decoded) != decoded:
        raise LiveConfigurationError(
            "invalid_config",
            "live API base host contains ambiguous encoding",
        )
    return decoded


def _is_loopback_api_host(host: str) -> bool:
    normalized = host.strip().casefold().rstrip(".")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _decode_api_base_path(path: str) -> str:
    decoded = unquote(path)
    if unquote(decoded) != decoded:
        raise LiveConfigurationError(
            "invalid_config",
            "live API base path contains ambiguous encoding",
        )
    return decoded


def _public_api_base(value: str) -> str:
    try:
        return _safe_api_base(value)
    except LiveConfigurationError:
        return "[REDACTED_API_BASE]"


def _safe_public_id(value: str, *, field_name: str) -> str:
    stripped = value.strip()
    if not stripped or not _PUBLIC_ID_PATTERN.fullmatch(stripped):
        raise LiveConfigurationError("invalid_config", f"{field_name} is invalid")
    if _SECRETISH_PATTERN.search(stripped):
        raise LiveConfigurationError(
            "invalid_config", f"{field_name} must not contain secrets"
        )
    return stripped


def _public_config_id(value: str) -> str:
    stripped = value.strip()
    if not _PUBLIC_ID_PATTERN.fullmatch(stripped):
        return _REDACTED_ID
    if _SECRETISH_PATTERN.search(stripped):
        return _REDACTED_ID
    return stripped


def _positive_float(raw: str | None, default: float, name: str) -> float:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise LiveConfigurationError(
            "invalid_config", f"{name} must be a number"
        ) from exc
    _require_positive_number(value, name)
    return value


def _require_positive_number(value: float, name: str) -> None:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise LiveConfigurationError("invalid_config", f"{name} must be positive")


def _require_nonnegative_number(value: float, name: str) -> None:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise LiveConfigurationError("invalid_config", f"{name} must be >= 0")


def _require_positive_int_value(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LiveConfigurationError("invalid_config", f"{name} must be positive")


def _require_nonnegative_int_value(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LiveConfigurationError("invalid_config", f"{name} must be >= 0")


def _nonnegative_float(raw: str | None, default: float, name: str) -> float:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise LiveConfigurationError(
            "invalid_config", f"{name} must be a number"
        ) from exc
    _require_nonnegative_number(value, name)
    return value


def _positive_int(raw: str | None, default: int, name: str) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise LiveConfigurationError(
            "invalid_config", f"{name} must be an integer"
        ) from exc
    if value <= 0:
        raise LiveConfigurationError("invalid_config", f"{name} must be positive")
    return value


def _nonnegative_int(raw: str | None, default: int, name: str) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise LiveConfigurationError(
            "invalid_config", f"{name} must be an integer"
        ) from exc
    if value < 0:
        raise LiveConfigurationError("invalid_config", f"{name} must be >= 0")
    return value
