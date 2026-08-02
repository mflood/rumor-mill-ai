"""Database engine and session construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_MIGRATION_DATABASE_URL = (
    "postgresql+psycopg://rumor_mill:rumor_mill@localhost:55432/rumor_mill"
)


def resolve_migration_database_url(configured_url: str, environment_url: str | None) -> str:
    """Let explicit Alembic configs win over the default environment override."""
    if environment_url and configured_url == DEFAULT_MIGRATION_DATABASE_URL:
        return environment_url
    return configured_url


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for Postgres or SQLite."""
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions with explicit transaction boundaries."""

    return sessionmaker(bind=engine, expire_on_commit=False)
