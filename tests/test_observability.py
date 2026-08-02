"""Structured telemetry, usage budgeting, and rate-limit coverage."""

import json
import logging
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from rumor_mill.adapters.providers import DeterministicFakeProvider
from rumor_mill.engine.ports import GenerationRequest, Message, MessageRole, ProviderRateLimitError
from rumor_mill.observability import (
    BudgetPolicy,
    JsonFormatter,
    MetricsRegistry,
    ObservedProvider,
    SlidingWindowRateLimiter,
    UsageBudget,
    bind_correlation,
    configure_json_logging,
    correlation_id,
    job_id,
    observed_job,
)


class ScenePlan(BaseModel):
    title: str
    tension: int


def generation_request() -> GenerationRequest:
    return GenerationRequest(
        messages=(Message(MessageRole.USER, "private conversation text"),),
        response_model=ScenePlan,
        purpose="scene-plan",
    )


def provider(*, operation: int = 100, daily: int = 100) -> tuple[ObservedProvider, MetricsRegistry]:
    metrics = MetricsRegistry()
    budget = UsageBudget(BudgetPolicy(operation, daily, 1, 2), metrics)
    fake = DeterministicFakeProvider({"scene-plan": {"title": "Signal", "tension": 3}})
    return ObservedProvider(fake, budget, metrics), metrics


def test_observed_provider_records_usage_cost_and_latency_without_prompts() -> None:
    observed, metrics = provider()

    observed.generate(generation_request())
    rendered = metrics.render()

    assert "rumor_mill_model_tokens_total" in rendered
    assert "rumor_mill_model_cost_usd_total" in rendered
    assert "rumor_mill_model_latency_seconds_total" in rendered
    assert "private conversation text" not in rendered


def test_operation_and_daily_budgets_cut_off_gracefully() -> None:
    operation_limited, operation_metrics = provider(operation=1)
    with pytest.raises(ProviderRateLimitError, match="operation budget"):
        operation_limited.generate(generation_request())
    assert 'scope="operation"' in operation_metrics.render()

    daily_limited, daily_metrics = provider(daily=1)
    with pytest.raises(ProviderRateLimitError, match="Daily model budget"):
        daily_limited.generate(generation_request())
    assert 'scope="daily"' in daily_metrics.render()

    already_spent, _ = provider(daily=10)
    already_spent._budget._tokens = 10
    with pytest.raises(ProviderRateLimitError, match="Daily model budget"):
        already_spent.generate(generation_request())


def test_stream_usage_is_recorded_once() -> None:
    observed, metrics = provider()
    list(observed.stream(generation_request()))
    assert metrics.render().count("rumor_mill_daily_model_tokens") == 1


def test_json_formatter_adds_correlation_without_private_fields() -> None:
    token = bind_correlation("request-123")
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "scene_started", (), None)
        record.purpose = "scene-plan"
        payload = json.loads(JsonFormatter().format(record))
    finally:
        correlation_id.reset(token)
    assert payload["correlation_id"] == "request-123"
    assert payload["purpose"] == "scene-plan"
    assert "private" not in payload

    job_token = job_id.set("job-4")
    try:
        without_request = json.loads(JsonFormatter().format(record))
    finally:
        job_id.reset(job_token)
    assert without_request["job_id"] == "job-4"
    assert "correlation_id" not in without_request


def test_json_logging_configures_existing_and_missing_handlers() -> None:
    root = logging.getLogger()
    original = root.handlers[:]
    try:
        root.handlers.clear()
        configure_json_logging()
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        existing = logging.StreamHandler()
        root.handlers[:] = [existing]
        configure_json_logging()
        assert isinstance(existing.formatter, JsonFormatter)
    finally:
        root.handlers[:] = original


def test_sliding_window_rate_limiter_recovers_after_window() -> None:
    limiter = SlidingWindowRateLimiter(2, window_seconds=10)
    assert limiter.allow("visitor", now=0)
    assert limiter.allow("visitor", now=1)
    assert not limiter.allow("visitor", now=2)
    assert limiter.allow("visitor", now=11)
    assert SlidingWindowRateLimiter(0).allow("visitor")
    assert SlidingWindowRateLimiter(1).allow("visitor")


def test_budget_rollover_and_provider_error_metrics() -> None:
    observed, metrics = provider()
    observed._budget._day = date.today() - timedelta(days=1)
    observed.generate(generation_request())
    assert observed._budget._day == date.today()

    failing = ObservedProvider(
        DeterministicFakeProvider({}, failure=ProviderRateLimitError()),
        observed._budget,
        metrics,
    )
    with pytest.raises(ProviderRateLimitError):
        failing.generate(generation_request())
    with pytest.raises(ProviderRateLimitError):
        list(failing.stream(generation_request()))
    assert metrics.render().count("rumor_mill_model_errors_total") == 1


def test_observed_job_binds_context_and_counts_failures() -> None:
    metrics = MetricsRegistry()
    job = SimpleNamespace(id="abc", kind="scene")

    def successful(item: object) -> tuple[str | None, str | None]:
        assert item is job
        return correlation_id.get(), job_id.get()

    assert observed_job(successful, metrics)(job) == ("job:abc", "abc")

    def failing(item: object) -> None:
        del item
        raise ValueError("private payload")

    with pytest.raises(ValueError, match="private payload"):
        observed_job(failing, metrics)(job)
    rendered = metrics.render()
    assert "rumor_mill_scene_failures_total" in rendered
    assert rendered.count("rumor_mill_job_latency_seconds_total") == 1
