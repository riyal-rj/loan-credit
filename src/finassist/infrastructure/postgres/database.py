"""Async SQLAlchemy engine/session factory bootstrap.

One `AsyncEngine` per process, built once at composition-root time from validated `Settings` --
no module-level global engine, so tests can build an independent engine against a disposable
container database (`tests/integration/conftest.py`).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from finassist.bootstrap.settings import Settings


def build_engine(settings: Settings, *, url: str | None = None) -> AsyncEngine:
    """Build an engine for ``url`` (default: ``settings.database_url``, the low-privilege
    application role). Alembic (`migrations/env.py`) passes ``settings.database_migration_url``
    explicitly instead -- migrations run as a more-privileged role than the application does."""
    return create_async_engine(
        url or settings.database_url,
        pool_size=settings.database_pool_min_size,
        max_overflow=max(settings.database_pool_max_size - settings.database_pool_min_size, 0),
        pool_pre_ping=True,
        connect_args={
            "command_timeout": settings.database_statement_timeout_seconds,
            "server_settings": {
                "statement_timeout": str(int(settings.database_statement_timeout_seconds * 1000))
            },
        },
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


async def check_connectivity(engine: AsyncEngine) -> None:
    """Open and immediately release one connection. Used by the `/health/ready` check -- a
    real network round trip to Postgres, not a pool-state guess. Raises on failure; the caller
    (a `ReadinessCheck`) treats any exception as "not ready"."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
