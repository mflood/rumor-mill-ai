"""Database engine and session construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_MIGRATION_DATABASE_URL = (
    "postgresql+psycopg://rumor_mill:rumor_mill@localhost:55432/rumor_mill"
)


def normalize_database_url(database_url: str) -> str:
    """Select the installed psycopg driver for standard and Heroku Postgres URLs."""
    for scheme in ("postgres://", "postgresql://"):
        if database_url.startswith(scheme):
            return database_url.replace(scheme, "postgresql+psycopg://", 1)
    return database_url


def resolve_migration_database_url(
    configured_url: str,
    explicit_environment_url: str | None,
    managed_environment_url: str | None = None,
) -> str:
    """Resolve migrations without overriding an explicitly configured Alembic database."""
    if configured_url == DEFAULT_MIGRATION_DATABASE_URL:
        configured_url = explicit_environment_url or managed_environment_url or configured_url
    return normalize_database_url(configured_url)


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for Postgres or SQLite."""
    return create_engine(normalize_database_url(database_url), echo=echo, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions with explicit transaction boundaries."""

    return sessionmaker(bind=engine, expire_on_commit=False)
