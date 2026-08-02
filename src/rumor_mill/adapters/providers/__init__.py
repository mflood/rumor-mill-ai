"""Model provider adapters and configuration factory."""

from collections.abc import Mapping
from typing import Any

from rumor_mill.adapters.persistence.llm_tracing import SqlAlchemyLlmTraceStore
from rumor_mill.adapters.providers.fake import DeterministicFakeProvider
from rumor_mill.adapters.providers.openai import OpenAIProvider
from rumor_mill.config import Settings
from rumor_mill.engine.ports import ModelProvider, ProviderAuthenticationError
from rumor_mill.observability import BudgetPolicy, MetricsRegistry, ObservedProvider, UsageBudget


def create_model_provider(
    settings: Settings,
    *,
    fake_responses: Mapping[str, Mapping[str, Any]] | None = None,
    metrics: MetricsRegistry | None = None,
    trace_store: SqlAlchemyLlmTraceStore | None = None,
) -> ModelProvider:
    """Create the configured adapter without reading configuration anywhere else."""

    if settings.model_provider == "fake":
        provider: ModelProvider = DeterministicFakeProvider(fake_responses or {})
    elif settings.model_provider == "openai":
        if settings.openai_api_key is None:
            raise ProviderAuthenticationError("OpenAI API key is not configured")
        provider = OpenAIProvider(settings, trace_sink=trace_store)
    else:
        raise ValueError(f"Unsupported model provider '{settings.model_provider}'")
    if metrics is None:
        return provider
    registry = metrics
    return ObservedProvider(
        provider,
        UsageBudget(
            BudgetPolicy(
                settings.operation_token_budget,
                settings.daily_token_budget,
                settings.estimated_cost_per_million_input_tokens,
                settings.estimated_cost_per_million_output_tokens,
            ),
            registry,
        ),
        registry,
    )


__all__ = ["DeterministicFakeProvider", "OpenAIProvider", "create_model_provider"]
