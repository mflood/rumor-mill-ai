"""Application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "Rumor Mill AI"
    environment: str = "development"
    database_url: str = "postgresql://rumor_mill:rumor_mill@localhost:5432/rumor_mill"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="RUMOR_MILL_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
