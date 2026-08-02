"""Model provider adapters and configuration factory."""

from collections.abc import Mapping
from typing import Any

from rumor_mill.adapters.providers.fake import DeterministicFakeProvider
from rumor_mill.adapters.providers.openai import OpenAIProvider
from rumor_mill.config import Settings
from rumor_mill.engine.ports import ModelProvider, ProviderAuthenticationError


def create_model_provider(
    settings: Settings, *, fake_responses: Mapping[str, Mapping[str, Any]] | None = None
) -> ModelProvider:
    """Create the configured adapter without reading configuration anywhere else."""

    if settings.model_provider == "fake":
        return DeterministicFakeProvider(fake_responses or {})
    if settings.model_provider == "openai":
        if settings.openai_api_key is None:
            raise ProviderAuthenticationError("OpenAI API key is not configured")
        return OpenAIProvider(settings)
    raise ValueError(f"Unsupported model provider '{settings.model_provider}'")


__all__ = ["DeterministicFakeProvider", "OpenAIProvider", "create_model_provider"]
