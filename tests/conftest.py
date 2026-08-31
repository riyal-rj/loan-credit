from __future__ import annotations

from collections.abc import Iterator

import pytest

from finassist.bootstrap.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Ensure `get_settings()` never leaks a cached instance across tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="local",
        service_name="finassist-test",
        log_format="console",
        otel_exporter_otlp_endpoint=None,
        otel_console_fallback=True,
    )
