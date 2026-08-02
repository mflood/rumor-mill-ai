"""OpenAI Responses API adapter."""

import logging
from collections.abc import Iterator
from typing import Any, cast

import openai
from openai import OpenAI
from openai.types.responses import EasyInputMessageParam, ResponseInputParam

from rumor_mill.config import Settings
from rumor_mill.engine.ports import (
    GenerationRequest,
    GenerationResult,
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

logger = logging.getLogger(__name__)


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        if settings.openai_api_key is None:
            raise ProviderAuthenticationError("OpenAI API key is not configured")
        self._model = settings.openai_model
        self._client = client or OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        logger.info(
            "model_generation_started",
            extra={
                "provider": self.provider_name,
                "model": self._model,
                "purpose": request.purpose,
            },
        )
        try:
            response = self._client.with_options(
                timeout=request.timeout_seconds, max_retries=request.max_retries
            ).responses.parse(
                model=self._model,
                input=self._messages(request),
                text_format=request.response_model,
                store=False,
            )
            return self._result(response)
        except ProviderError:
            raise
        except Exception as exc:
            error = normalize_openai_error(exc)
            logger.warning(
                "model_generation_failed",
                extra={
                    "provider": self.provider_name,
                    "model": self._model,
                    "error_code": error.code,
                },
            )
            raise error from exc

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]:
        try:
            client = self._client.with_options(
                timeout=request.timeout_seconds, max_retries=request.max_retries
            )
            with client.responses.stream(
                model=self._model,
                input=self._messages(request),
                text_format=request.response_model,
                store=False,
            ) as stream:
                for raw_event in stream:
                    event: Any = raw_event
                    if event.type == "response.output_text.delta":
                        yield StreamEvent(kind=StreamEventKind.TEXT_DELTA, delta=event.delta)
                yield StreamEvent(
                    kind=StreamEventKind.COMPLETED,
                    result=self._result(stream.get_final_response()),
                )
        except ProviderError:
            raise
        except Exception as exc:
            raise normalize_openai_error(exc) from exc

    def _result(self, response: Any) -> GenerationResult:
        if response.output_parsed is None:
            raise ProviderResponseError("Provider returned no structured response")
        usage = response.usage
        if usage is None:
            normalized_usage = Usage(input_tokens=0, output_tokens=0, total_tokens=0)
        else:
            normalized_usage = Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            )
        return GenerationResult(
            data=response.output_parsed,
            usage=normalized_usage,
            provider=self.provider_name,
            model=response.model,
            request_id=response.id,
        )

    @staticmethod
    def _messages(request: GenerationRequest) -> ResponseInputParam:
        return [
            EasyInputMessageParam(role=cast(Any, message.role.value), content=message.content)
            for message in request.messages
        ]


def normalize_openai_error(error: Exception) -> ProviderError:
    """Map SDK failures to stable errors without copying sensitive messages."""

    if isinstance(error, openai.APITimeoutError):
        return ProviderTimeoutError()
    if isinstance(error, openai.RateLimitError):
        return ProviderRateLimitError()
    if isinstance(error, openai.AuthenticationError):
        return ProviderAuthenticationError()
    if isinstance(error, openai.APIConnectionError | openai.InternalServerError):
        return ProviderUnavailableError()
    return ProviderError()
