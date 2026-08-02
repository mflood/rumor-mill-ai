"""Normalized model-provider failures safe to surface and log."""


class ProviderError(RuntimeError):
    code = "provider_error"
    retryable = False

    def __init__(self, message: str = "Model provider request failed") -> None:
        super().__init__(message)


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    retryable = True


class ProviderRateLimitError(ProviderError):
    code = "provider_rate_limit"
    retryable = True


class ProviderAuthenticationError(ProviderError):
    code = "provider_authentication"


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    retryable = True


class ProviderResponseError(ProviderError):
    code = "provider_response"
