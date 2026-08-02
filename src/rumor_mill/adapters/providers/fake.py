"""Deterministic, zero-cost provider for tests and demo mode."""

import json
from collections.abc import Iterator, Mapping
from typing import Any

from rumor_mill.engine.ports import (
    GenerationRequest,
    GenerationResult,
    ProviderError,
    ProviderResponseError,
    StreamEvent,
    StreamEventKind,
    Usage,
)


class DeterministicFakeProvider:
    provider_name = "fake"
    model_name = "deterministic-v1"

    def __init__(
        self,
        responses: Mapping[str, Mapping[str, Any]],
        *,
        failure: ProviderError | None = None,
        chunk_size: int = 16,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._responses = dict(responses)
        self._failure = failure
        self._chunk_size = chunk_size

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if self._failure is not None:
            raise self._failure
        payload = self._responses.get(request.purpose)
        if payload is None:
            raise ProviderResponseError(f"No fake response registered for '{request.purpose}'")
        data = request.response_model.model_validate(payload)
        serialized = data.model_dump_json()
        input_tokens = sum(len(message.content.split()) for message in request.messages)
        output_tokens = len(serialized.split())
        return GenerationResult(
            data=data,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            provider=self.provider_name,
            model=self.model_name,
            request_id=f"fake:{request.purpose}",
        )

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]:
        result = self.generate(request)
        serialized = json.dumps(result.data.model_dump(mode="json"), sort_keys=True)
        for index in range(0, len(serialized), self._chunk_size):
            yield StreamEvent(
                kind=StreamEventKind.TEXT_DELTA,
                delta=serialized[index : index + self._chunk_size],
            )
        yield StreamEvent(kind=StreamEventKind.COMPLETED, result=result)
