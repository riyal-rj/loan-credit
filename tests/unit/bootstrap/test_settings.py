from __future__ import annotations

import pytest
from pydantic import ValidationError

from finassist.bootstrap.settings import SecretProviderKind, Settings, get_settings


def test_defaults_are_safe_for_local_development() -> None:
    settings = Settings()
    assert settings.environment.value == "local"
    assert settings.secret_provider is SecretProviderKind.ENV


def test_production_requires_openbao_secret_provider() -> None:
    with pytest.raises(ValidationError, match="secret_provider=openbao"):
        Settings(
            environment="production",
            secret_provider="env",
            log_format="json",
            otel_console_fallback=False,
        )


def test_production_requires_json_logging() -> None:
    with pytest.raises(ValidationError, match="log_format=json"):
        Settings(
            environment="production",
            secret_provider="openbao",
            log_format="console",
            otel_console_fallback=False,
        )


def test_production_rejects_console_trace_fallback() -> None:
    with pytest.raises(ValidationError, match="must not fall back to console trace export"):
        Settings(
            environment="production",
            secret_provider="openbao",
            log_format="json",
            otel_console_fallback=True,
        )


def test_valid_production_configuration_is_accepted() -> None:
    settings = Settings(
        environment="production",
        secret_provider="openbao",
        log_format="json",
        otel_console_fallback=False,
        otel_exporter_otlp_endpoint="http://otel-collector:4318",
        database_url="postgresql+asyncpg://prod-app:prod-app-pass@prod-host:5432/finassist",
        database_migration_url="postgresql+asyncpg://prod-migrator:prod-migrator-pass@prod-host:5432/finassist",
    )
    assert settings.environment.value == "production"


def test_production_rejects_default_local_database_url() -> None:
    with pytest.raises(ValidationError, match="local-dev default database_url"):
        Settings(
            environment="production",
            secret_provider="openbao",
            log_format="json",
            otel_console_fallback=False,
            otel_exporter_otlp_endpoint="http://otel-collector:4318",
            database_migration_url="postgresql+asyncpg://prod-migrator:prod-migrator-pass@prod-host:5432/finassist",
        )


def test_production_rejects_default_local_migration_database_url() -> None:
    with pytest.raises(ValidationError, match="local-dev default database_migration_url"):
        Settings(
            environment="production",
            secret_provider="openbao",
            log_format="json",
            otel_console_fallback=False,
            otel_exporter_otlp_endpoint="http://otel-collector:4318",
            database_url="postgresql+asyncpg://prod-app:prod-app-pass@prod-host:5432/finassist",
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(this_field_does_not_exist="oops")  # type: ignore[call-arg]


def test_get_settings_is_cached_singleton() -> None:
    first = get_settings()
    second = get_settings()
    assert first is second


def test_invalid_port_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(http_port=0)
    with pytest.raises(ValidationError):
        Settings(http_port=70000)
