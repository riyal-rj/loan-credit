"""Integration test fixtures: a real, disposable PostgreSQL container (master instruction §21.1:
"Repository integration tests against real PostgreSQL containers").

One container per test session (starting it is the slow part); each test generates its own fresh
tenant/product/application IDs, so tests never need to truncate tables between runs to stay
isolated from each other.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from finassist.bootstrap.settings import get_settings
from finassist.infrastructure.postgres.database import build_engine, build_session_factory


@pytest.fixture(scope="session")
def _monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="session")
def _postgres_urls(_monkeypatch_session: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    """Start the container and set both the migration (superuser) and application (low-privilege
    `finassist_app`) database URLs.

    A container's bootstrap role is always a superuser, so it stands in for `finassist`
    (migrations). `finassist_app` is created by the migration itself (docs/adr/0009) -- the app
    URL just swaps credentials on the same host/port/database the container already exposes.
    """
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        migration_url = postgres.get_connection_url()
        # `str(url)` masks the password as "***" by default (SQLAlchemy's repr-safety default) --
        # must use render_as_string(hide_password=False) or asyncpg receives the literal "***".
        app_url = (
            make_url(migration_url)
            .set(username="finassist_app", password="finassist_app")
            .render_as_string(hide_password=False)
        )

        _monkeypatch_session.setenv("FINASSIST_DATABASE_MIGRATION_URL", migration_url)
        _monkeypatch_session.setenv("FINASSIST_DATABASE_URL", app_url)
        get_settings.cache_clear()
        yield migration_url, app_url


@pytest.fixture(scope="session")
def postgres_url(_postgres_urls: tuple[str, str]) -> str:
    return _postgres_urls[1]


@pytest.fixture(scope="session")
def _migrated_database(_postgres_urls: tuple[str, str]) -> None:
    migration_url, _app_url = _postgres_urls
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", migration_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database_engine(
    postgres_url: str, _migrated_database: None
) -> AsyncIterator[AsyncEngine]:
    """Engine bound to the low-privilege `finassist_app` role -- what the application itself
    (and therefore most test assertions) uses."""
    engine = build_engine(get_settings())
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(database_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return build_session_factory(database_engine)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_engine(
    _postgres_urls: tuple[str, str], _migrated_database: None
) -> AsyncIterator[AsyncEngine]:
    """Engine bound to the migration (superuser) role -- for test setup steps that are
    legitimately administrative, like onboarding a new tenant (`identity.tenants` grants
    `finassist_app` `SELECT` only, matching real tenant-onboarding being an admin action, not
    something the running application does to itself)."""
    migration_url, _app_url = _postgres_urls
    engine = build_engine(get_settings(), url=migration_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def admin_session_factory(admin_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return build_session_factory(admin_engine)
