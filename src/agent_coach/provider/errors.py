"""Bounded live-provider errors. Messages must not include secrets or raw payloads."""


class LiveConfigurationError(ValueError):
    """Fail-closed startup error for missing SDK, key or unsafe cost config."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


UNKNOWN_PRICING_MESSAGE = "cost cap is active and cloud pricing is unknown"


class ProviderAdapterError(RuntimeError):
    """Fail-closed provider call or native-tool error."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(message)
