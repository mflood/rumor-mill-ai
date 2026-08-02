"""OpenAI Responses API adapter."""

import logging
import time
from collections.abc import Iterator, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

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


class LlmTraceSink(Protocol):
    def record_outbound(
        self,
        *,
        call_id: UUID,
        provider: str,
        model: str,
        purpose: str,
        messages: Sequence[dict[str, Any]],
    ) -> None: ...

    def record_inbound(
        self,
        *,
        call_id: UUID,
        sequence: int,
        provider: str,
        model: str,
        purpose: str,
        item_type: str,
        payload: dict[str, Any],
        duration_ms: int | None = None,
    ) -> None: ...


class OpenAIProvider:
    provider_name = "openai"

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        trace_sink: LlmTraceSink | None = None,
    ) -> None:
        if settings.openai_api_key is None:
            raise ProviderAuthenticationError("OpenAI API key is not configured")
        self._model = settings.openai_model
        self._trace_sink = trace_sink
        self._client = client or OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        call_id, messages, started = self._start_trace(request)
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
                input=messages,
                text_format=request.response_model,
                store=False,
            )
            self._trace_inbound(
                call_id,
                request,
                0,
                "response",
                _json_payload(response),
                started,
            )
            return self._result(response)
        except ProviderError:
            raise
        except Exception as exc:
            error = normalize_openai_error(exc)
            self._trace_inbound(
                call_id,
                request,
                0,
                "error",
                {"error_code": error.code, "retryable": error.retryable},
                started,
            )
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
        call_id, messages, started = self._start_trace(request)
        sequence = 0
        try:
            client = self._client.with_options(
                timeout=request.timeout_seconds, max_retries=request.max_retries
            )
            with client.responses.stream(
                model=self._model,
                input=messages,
                text_format=request.response_model,
                store=False,
            ) as stream:
                for raw_event in stream:
                    event: Any = raw_event
                    self._trace_inbound(
                        call_id, request, sequence, "response_event", _json_payload(event)
                    )
                    sequence += 1
                    if event.type == "response.output_text.delta":
                        yield StreamEvent(kind=StreamEventKind.TEXT_DELTA, delta=event.delta)
                final_response = stream.get_final_response()
                self._trace_inbound(
                    call_id,
                    request,
                    sequence,
                    "response",
                    _json_payload(final_response),
                    started,
                )
                yield StreamEvent(
                    kind=StreamEventKind.COMPLETED,
                    result=self._result(final_response),
                )
        except ProviderError:
            raise
        except Exception as exc:
            error = normalize_openai_error(exc)
            self._trace_inbound(
                call_id,
                request,
                sequence,
                "error",
                {"error_code": error.code, "retryable": error.retryable},
                started,
            )
            raise error from exc

    def _start_trace(self, request: GenerationRequest) -> tuple[UUID, ResponseInputParam, float]:
        call_id = uuid4()
        messages = self._messages(request)
        if self._trace_sink is not None:
            self._trace_sink.record_outbound(
                call_id=call_id,
                provider=self.provider_name,
                model=self._model,
                purpose=request.purpose,
                messages=cast(list[dict[str, Any]], messages),
            )
        started = time.monotonic()
        return call_id, messages, started

    def _trace_inbound(
        self,
        call_id: UUID,
        request: GenerationRequest,
        sequence: int,
        item_type: str,
        payload: dict[str, Any],
        started: float | None = None,
    ) -> None:
        if self._trace_sink is None:
            return
        duration_ms = None if started is None else round((time.monotonic() - started) * 1000)
        self._trace_sink.record_inbound(
            call_id=call_id,
            sequence=sequence,
            provider=self.provider_name,
            model=self._model,
            purpose=request.purpose,
            item_type=item_type,
            payload=payload,
            duration_ms=duration_ms,
        )

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


def _json_payload(value: Any) -> dict[str, Any]:
    """Convert SDK response/event models to JSON-safe data without dropping raw fields."""

    normalized = _json_value(value)
    return normalized if isinstance(normalized, dict) else {"value": normalized}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseException):
        return {"type": type(value).__name__}
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _json_value(asdict(cast(Any, value)))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_value(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


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
