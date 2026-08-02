"""Privacy-safe structured telemetry, model budgets, and request rate limits."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from rumor_mill.engine.ports import (
    GenerationRequest,
    GenerationResult,
    ModelProvider,
    ProviderError,
    ProviderRateLimitError,
    StreamEvent,
    StreamEventKind,
)

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
job_id: ContextVar[str | None] = ContextVar("job_id", default=None)


def bind_correlation(value: str | None = None) -> Token[str | None]:
    return correlation_id.set(value or str(uuid4()))


class JsonFormatter(logging.Formatter):
    """Format records as single-line JSON without inspecting message payloads."""

    _fields = (
        "provider",
        "model",
        "purpose",
        "error_code",
        "method",
        "path",
        "status_code",
        "playable_story_available",
        "readiness_reason",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        if value := correlation_id.get():
            payload["correlation_id"] = value
        if value := job_id.get():
            payload["job_id"] = value
        for field in self._fields:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_json_logging() -> None:
    """Configure application logs for production without duplicating handlers."""

    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    formatter = JsonFormatter()
    for handler in root.handlers:
        handler.setFormatter(formatter)


class MetricsRegistry:
    """Small dependency-free registry exporting the Prometheus text format."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    @staticmethod
    def _key(name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        return name, tuple(sorted(labels.items()))

    def increment(self, name: str, amount: float = 1, **labels: str) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += amount

    def set(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def render(self) -> str:
        with self._lock:
            values = [*self._counters.items(), *self._gauges.items()]
        lines = []
        for (name, labels), value in sorted(values):
            suffix = ""
            if labels:
                encoded = ",".join(
                    f'{key}="{val.replace(chr(34), chr(92) + chr(34))}"' for key, val in labels
                )
                suffix = "{" + encoded + "}"
            lines.append(f"rumor_mill_{name}{suffix} {value:g}")
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    per_operation_tokens: int
    daily_tokens: int
    input_cost_per_million: float
    output_cost_per_million: float


class UsageBudget:
    def __init__(self, policy: BudgetPolicy, metrics: MetricsRegistry) -> None:
        self.policy = policy
        self.metrics = metrics
        self._lock = threading.Lock()
        self._day = date.today()
        self._tokens = 0

    def allow(self, purpose: str) -> None:
        with self._lock:
            self._rollover()
            if self.policy.daily_tokens and self._tokens >= self.policy.daily_tokens:
                self.metrics.increment("budget_cutoffs_total", purpose=purpose, scope="daily")
                raise ProviderRateLimitError("Daily model budget has been reached")

    def record(self, purpose: str, result: GenerationResult) -> None:
        usage = result.usage
        if (
            self.policy.per_operation_tokens
            and usage.total_tokens > self.policy.per_operation_tokens
        ):
            self.metrics.increment("budget_cutoffs_total", purpose=purpose, scope="operation")
            raise ProviderRateLimitError("Model operation budget has been exceeded")
        with self._lock:
            self._rollover()
            if (
                self.policy.daily_tokens
                and self._tokens + usage.total_tokens > self.policy.daily_tokens
            ):
                self.metrics.increment("budget_cutoffs_total", purpose=purpose, scope="daily")
                raise ProviderRateLimitError("Daily model budget has been reached")
            self._tokens += usage.total_tokens
            self.metrics.set("daily_model_tokens", self._tokens)
        cost = (
            usage.input_tokens * self.policy.input_cost_per_million
            + usage.output_tokens * self.policy.output_cost_per_million
        ) / 1_000_000
        for kind, amount in (("input", usage.input_tokens), ("output", usage.output_tokens)):
            self.metrics.increment("model_tokens_total", amount, purpose=purpose, kind=kind)
        self.metrics.increment("model_cost_usd_total", cost, purpose=purpose)

    def _rollover(self) -> None:
        today = date.today()
        if today != self._day:
            self._day, self._tokens = today, 0


class ObservedProvider:
    """Provider decorator enforcing budgets and emitting usage/error/latency metrics."""

    def __init__(
        self, wrapped: ModelProvider, budget: UsageBudget, metrics: MetricsRegistry
    ) -> None:
        self._wrapped, self._budget, self._metrics = wrapped, budget, metrics

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self._budget.allow(request.purpose)
        started = time.monotonic()
        try:
            result = self._wrapped.generate(request)
            self._budget.record(request.purpose, result)
            return result
        except ProviderError as exc:
            self._metrics.increment("model_errors_total", purpose=request.purpose, code=exc.code)
            raise
        finally:
            self._metrics.increment(
                "model_latency_seconds_total", time.monotonic() - started, purpose=request.purpose
            )

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]:
        self._budget.allow(request.purpose)
        started = time.monotonic()
        try:
            for event in self._wrapped.stream(request):
                if event.kind is StreamEventKind.COMPLETED and event.result is not None:
                    self._budget.record(request.purpose, event.result)
                yield event
        except ProviderError as exc:
            self._metrics.increment("model_errors_total", purpose=request.purpose, code=exc.code)
            raise
        finally:
            self._metrics.increment(
                "model_latency_seconds_total", time.monotonic() - started, purpose=request.purpose
            )


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, *, window_seconds: float = 60) -> None:
        self.limit, self.window_seconds = limit, window_seconds
        self._lock = threading.Lock()
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        if not self.limit:
            return True
        current = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._requests[key]
            while bucket and bucket[0] <= current - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(current)
            return True


def observed_job(handler: Callable[..., Any], metrics: MetricsRegistry) -> Callable[..., Any]:
    """Decorate a job handler with correlation and failure metrics."""

    def wrapped(job: Any) -> Any:
        token = job_id.set(str(job.id))
        correlation = bind_correlation(f"job:{job.id}")
        started = time.monotonic()
        try:
            return handler(job)
        except Exception:
            metrics.increment("scene_failures_total", kind=str(job.kind))
            raise
        finally:
            metrics.increment(
                "job_latency_seconds_total", time.monotonic() - started, kind=str(job.kind)
            )
            correlation_id.reset(correlation)
            job_id.reset(token)

    return wrapped
