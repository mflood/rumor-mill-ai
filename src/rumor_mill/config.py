"""Application configuration."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "Rumor Mill AI"
    environment: str = "development"
    database_url: str = "postgresql://rumor_mill:rumor_mill@localhost:55432/rumor_mill"
    model_provider: str = "fake"
    operator_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_timeout_seconds: float = Field(default=60.0, gt=0)
    openai_max_retries: int = Field(default=2, ge=0, le=10)

    model_config = SettingsConfigDict(env_file=".env", env_prefix="RUMOR_MILL_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
