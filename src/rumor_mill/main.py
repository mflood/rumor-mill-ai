"""FastAPI application entrypoint."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from rumor_mill.config import get_settings


class HealthResponse(BaseModel):
    """Health-check response schema."""

    status: Literal["ok"]
    environment: str


def create_app() -> FastAPI:
    """Build and configure the application."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", environment=settings.environment)

    return app


app = create_app()
