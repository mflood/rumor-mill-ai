"""Application configuration."""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "Rumor Mill AI"
    environment: str = "development"
    database_url: str = Field(  # type: ignore[pydantic-alias]
        default="postgresql://rumor_mill:rumor_mill@localhost:55432/rumor_mill",
        validation_alias=AliasChoices("RUMOR_MILL_DATABASE_URL", "DATABASE_URL"),
    )
    model_provider: str = "fake"
    operator_api_key: SecretStr | None = None
    metrics_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_timeout_seconds: float = Field(default=60.0, gt=0)
    openai_max_retries: int = Field(default=2, ge=0, le=10)
    visitor_session_days: int = Field(default=365, ge=1, le=730)
    secure_visitor_cookie: bool = True
    conversation_message_limit: int = Field(default=50, ge=1, le=500)
    operation_token_budget: int = Field(default=20_000, ge=0)
    daily_token_budget: int = Field(default=1_000_000, ge=0)
    estimated_cost_per_million_input_tokens: float = Field(default=1.25, ge=0)
    estimated_cost_per_million_output_tokens: float = Field(default=10.0, ge=0)
    requests_per_minute: int = Field(default=120, ge=0)
    active_visitor_window_minutes: int = Field(default=15, ge=1)
    worker_stale_after_seconds: int = Field(default=600, ge=1)
    worker_poll_seconds: float = Field(default=5.0, gt=0, le=300)
    worker_run_batch_size: int = Field(default=100, ge=1, le=1_000)
    worker_job_batch_size: int = Field(default=100, ge=1, le=1_000)
    provider_health_required: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_prefix="RUMOR_MILL_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
