"""Provider contract, deterministic fake, and OpenAI adapter tests."""

import logging
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from rumor_mill.adapters.providers import (
    DeterministicFakeProvider,
    OpenAIProvider,
    create_model_provider,
)
from rumor_mill.adapters.providers.openai import normalize_openai_error
from rumor_mill.config import Settings
from rumor_mill.engine.ports import (
    GenerationRequest,
    GenerationResult,
    Message,
    MessageRole,
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StreamEvent,
    StreamEventKind,
    Usage,
)


class ScenePlan(BaseModel):
    title: str
    tension: int


def request() -> GenerationRequest:
    return GenerationRequest(
        messages=(
            Message(MessageRole.DEVELOPER, "Keep the private world canon intact."),
            Message(MessageRole.USER, "Write the next secret scene."),
        ),
        response_model=ScenePlan,
        purpose="scene-plan",
        timeout_seconds=12.5,
        max_retries=4,
    )


def result() -> GenerationResult:
    return GenerationResult(
        data=ScenePlan(title="The Signal", tension=7),
        usage=Usage(input_tokens=8, output_tokens=4, total_tokens=12),
        provider="test",
        model="test-model",
        request_id="request-1",
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"messages": ()}, "at least one message"),
        ({"timeout_seconds": 0}, "must be positive"),
        ({"max_retries": -1}, "cannot be negative"),
    ],
)
def test_generation_request_rejects_invalid_policy(kwargs: dict[str, Any], message: str) -> None:
    values: dict[str, Any] = {
        "messages": (Message(MessageRole.USER, "hello"),),
        "response_model": ScenePlan,
        "purpose": "test",
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        GenerationRequest(**values)


def test_deterministic_fake_generates_typed_result_and_stream() -> None:
    provider = DeterministicFakeProvider(
        {"scene-plan": {"title": "The Signal", "tension": 7}}, chunk_size=10
    )

    first = provider.generate(request())
    second = provider.generate(request())
    events = tuple(provider.stream(request()))

    assert first == second
    assert first.data == ScenePlan(title="The Signal", tension=7)
    assert first.provider == "fake"
    assert first.usage.total_tokens == first.usage.input_tokens + first.usage.output_tokens
    assert "".join(event.delta or "" for event in events[:-1]) == (
        '{"tension": 7, "title": "The Signal"}'
    )
    assert events[-1] == StreamEvent(kind=StreamEventKind.COMPLETED, result=first)


def test_fake_rejects_bad_configuration_and_missing_fixture() -> None:
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        DeterministicFakeProvider({}, chunk_size=0)

    provider = DeterministicFakeProvider({})
    with pytest.raises(ProviderResponseError, match="No fake response registered"):
        provider.generate(request())


def test_fake_propagates_normalized_failure_and_validates_fixture() -> None:
    failure = ProviderTimeoutError()
    provider = DeterministicFakeProvider({}, failure=failure)
    with pytest.raises(ProviderTimeoutError):
        provider.generate(request())

    invalid = DeterministicFakeProvider({"scene-plan": {"title": "Missing tension"}})
    with pytest.raises(ValidationError):
        invalid.generate(request())


def test_stream_event_enforces_shape() -> None:
    completed = result()
    assert StreamEvent(kind=StreamEventKind.TEXT_DELTA, delta="{").delta == "{"
    assert StreamEvent(kind=StreamEventKind.COMPLETED, result=completed).result == completed

    with pytest.raises(ValueError, match="text delta events require only delta"):
        StreamEvent(kind=StreamEventKind.TEXT_DELTA)
    with pytest.raises(ValueError, match="text delta events require only delta"):
        StreamEvent(kind=StreamEventKind.COMPLETED, delta="unexpected", result=completed)
    with pytest.raises(ValueError, match="completed events require only result"):
        StreamEvent(kind=StreamEventKind.COMPLETED)
    with pytest.raises(ValueError, match="completed events require only result"):
        StreamEvent(kind=StreamEventKind.TEXT_DELTA, delta="ok", result=completed)


class ResponseStub:
    def __init__(self, *, parsed: BaseModel | None = None, usage: Any | None = None) -> None:
        self.id = "response-123"
        self.model = "gpt-test"
        self.output_parsed = parsed
        self.usage = usage


class StreamManagerStub:
    def __init__(self, response: ResponseStub) -> None:
        self._response = response

    def __enter__(self) -> "StreamManagerStub":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def __iter__(self) -> Any:
        return iter(
            (
                SimpleNamespace(type="response.created"),
                SimpleNamespace(type="response.output_text.delta", delta="partial"),
            )
        )

    def get_final_response(self) -> ResponseStub:
        return self._response


class ClientStub:
    def __init__(
        self,
        response: ResponseStub | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response or ResponseStub(parsed=ScenePlan(title="The Signal", tension=7))
        self.error = error
        self.options: dict[str, Any] = {}
        self.parse_arguments: dict[str, Any] = {}
        self.stream_arguments: dict[str, Any] = {}
        self.responses = self

    def with_options(self, **kwargs: Any) -> "ClientStub":
        self.options = kwargs
        return self

    def parse(self, **kwargs: Any) -> ResponseStub:
        self.parse_arguments = kwargs
        if self.error is not None:
            raise self.error
        return self.response

    def stream(self, **kwargs: Any) -> StreamManagerStub:
        self.stream_arguments = kwargs
        if self.error is not None:
            raise self.error
        return StreamManagerStub(self.response)


def openai_settings() -> Settings:
    return Settings(
        model_provider="openai",
        openai_api_key=SecretStr("top-secret-api-key"),
        openai_model="gpt-test",
        _env_file=None,
    )


def test_openai_adapter_generates_without_logging_secrets_or_prompts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15)
    client = ClientStub(ResponseStub(parsed=ScenePlan(title="The Signal", tension=7), usage=usage))
    provider = OpenAIProvider(openai_settings(), client=client)

    with caplog.at_level(logging.INFO):
        generated = provider.generate(request())

    assert generated.data == ScenePlan(title="The Signal", tension=7)
    assert generated.usage == Usage(input_tokens=10, output_tokens=5, total_tokens=15)
    assert generated.request_id == "response-123"
    assert client.options == {"timeout": 12.5, "max_retries": 4}
    assert client.parse_arguments["text_format"] is ScenePlan
    assert client.parse_arguments["store"] is False
    assert client.parse_arguments["input"][0] == {
        "role": "developer",
        "content": "Keep the private world canon intact.",
    }
    logs = caplog.text
    assert "top-secret-api-key" not in logs
    assert "private world canon" not in logs
    assert "next secret scene" not in logs


def test_openai_adapter_streams_typed_completion() -> None:
    client = ClientStub(ResponseStub(parsed=ScenePlan(title="The Signal", tension=7)))
    provider = OpenAIProvider(openai_settings(), client=client)

    events = tuple(provider.stream(request()))

    assert events[0] == StreamEvent(kind=StreamEventKind.TEXT_DELTA, delta="partial")
    assert events[1].kind is StreamEventKind.COMPLETED
    assert events[1].result is not None
    assert events[1].result.data == ScenePlan(title="The Signal", tension=7)
    assert events[1].result.usage == Usage(0, 0, 0)
    assert client.stream_arguments["text_format"] is ScenePlan
    assert client.stream_arguments["store"] is False


def test_openai_adapter_rejects_missing_structured_response() -> None:
    provider = OpenAIProvider(openai_settings(), client=ClientStub(ResponseStub()))

    with pytest.raises(ProviderResponseError, match="no structured response"):
        provider.generate(request())
    with pytest.raises(ProviderResponseError, match="no structured response"):
        tuple(provider.stream(request()))


def test_openai_adapter_normalizes_and_safely_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    raw_error = ValueError("private world canon and top-secret-api-key")
    provider = OpenAIProvider(openai_settings(), client=ClientStub(error=raw_error))

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderError) as error:
        provider.generate(request())

    assert error.value.code == "provider_error"
    assert "private world canon" not in caplog.text
    assert "top-secret-api-key" not in caplog.text


def test_openai_stream_normalizes_error() -> None:
    provider = OpenAIProvider(openai_settings(), client=ClientStub(error=ValueError("secret")))

    with pytest.raises(ProviderError) as error:
        tuple(provider.stream(request()))

    assert error.value.code == "provider_error"


def test_openai_configuration_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUMOR_MILL_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("RUMOR_MILL_OPENAI_API_KEY", "environment-secret")
    monkeypatch.setenv("RUMOR_MILL_OPENAI_MODEL", "environment-model")
    monkeypatch.setenv("RUMOR_MILL_OPENAI_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("RUMOR_MILL_OPENAI_MAX_RETRIES", "3")

    settings = Settings(_env_file=None)

    assert settings.model_provider == "openai"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "environment-secret"
    assert settings.openai_model == "environment-model"
    assert settings.openai_timeout_seconds == 9
    assert settings.openai_max_retries == 3


def test_provider_factory_supports_fake_openai_and_rejects_invalid_configuration() -> None:
    fake = create_model_provider(
        Settings(_env_file=None), fake_responses={"scene-plan": {"title": "Free", "tension": 1}}
    )
    assert isinstance(fake, DeterministicFakeProvider)

    client_provider = create_model_provider(openai_settings())
    assert isinstance(client_provider, OpenAIProvider)

    with pytest.raises(ProviderAuthenticationError, match="not configured"):
        create_model_provider(Settings(model_provider="openai", _env_file=None))
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_model_provider(Settings(model_provider="unknown", _env_file=None))


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(ProviderAuthenticationError, match="not configured"):
        OpenAIProvider(Settings(_env_file=None), client=ClientStub())


@pytest.mark.parametrize(
    ("sdk_error", "expected_type", "code", "retryable"),
    [
        (
            openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")),
            ProviderTimeoutError,
            "provider_timeout",
            True,
        ),
        (
            openai.RateLimitError(
                "limited",
                response=httpx.Response(
                    429, request=httpx.Request("POST", "https://api.openai.com")
                ),
                body=None,
            ),
            ProviderRateLimitError,
            "provider_rate_limit",
            True,
        ),
        (
            openai.AuthenticationError(
                "bad key",
                response=httpx.Response(
                    401, request=httpx.Request("POST", "https://api.openai.com")
                ),
                body=None,
            ),
            ProviderAuthenticationError,
            "provider_authentication",
            False,
        ),
        (
            openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")),
            ProviderUnavailableError,
            "provider_unavailable",
            True,
        ),
        (
            openai.InternalServerError(
                "down",
                response=httpx.Response(
                    500, request=httpx.Request("POST", "https://api.openai.com")
                ),
                body=None,
            ),
            ProviderUnavailableError,
            "provider_unavailable",
            True,
        ),
        (ValueError("private prompt"), ProviderError, "provider_error", False),
    ],
)
def test_openai_errors_are_normalized(
    sdk_error: Exception,
    expected_type: type[ProviderError],
    code: str,
    retryable: bool,
) -> None:
    normalized = normalize_openai_error(sdk_error)

    assert type(normalized) is expected_type
    assert normalized.code == code
    assert normalized.retryable is retryable
    assert "private prompt" not in str(normalized)
