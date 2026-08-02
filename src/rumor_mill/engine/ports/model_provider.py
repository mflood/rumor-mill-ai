"""Provider-neutral structured model generation contract."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class MessageRole(StrEnum):
    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str
    private: bool = True


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    messages: tuple[Message, ...]
    response_model: type[BaseModel]
    purpose: str
    timeout_seconds: float = 60.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("generation requires at least one message")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class GenerationResult:
    data: BaseModel
    usage: Usage
    provider: str
    model: str
    request_id: str


class StreamEventKind(StrEnum):
    TEXT_DELTA = "text_delta"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    kind: StreamEventKind
    delta: str | None = None
    result: GenerationResult | None = None

    def __post_init__(self) -> None:
        if (self.kind is StreamEventKind.TEXT_DELTA) != (self.delta is not None):
            raise ValueError("text delta events require only delta")
        if (self.kind is StreamEventKind.COMPLETED) != (self.result is not None):
            raise ValueError("completed events require only result")


class ModelProvider(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]: ...
