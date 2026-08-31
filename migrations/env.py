"""Alembic environment: runs migrations through the same settings module the app uses, but with
the application's own `database_url`.

`sqlalchemy.url` in `alembic.ini` is a placeholder -- the real URL always comes from
`finassist.bootstrap.settings.get_settings().database_migration_url` (or
`FINASSIST_DATABASE_MIGRATION_URL`), which is deliberately a *different, more privileged* role
than `database_url`: PostgreSQL exempts superusers from row-level security even with FORCE ROW
LEVEL SECURITY, so migrations (which need DDL privileges) and the application (which must be
subject to RLS) can never safely share one role. See docs/adr/0009.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from finassist.bootstrap.settings import get_settings
from finassist.infrastructure.postgres.database import build_engine
from finassist.infrastructure.postgres.orm_models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        version_table_schema="public",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    settings = get_settings()
    connectable: AsyncEngine = build_engine(settings, url=settings.database_migration_url)

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)

    await connectable.dispose()


def run_migrations_offline() -> None:
    settings = get_settings()
    context.configure(
        url=settings.database_migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
