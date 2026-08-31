"""Validated application settings.

All configuration enters the system through this module. Nothing else may read `os.environ`
directly (enforced by code review / import-linter in a later phase once more modules exist).
Settings fail fast: an invalid or missing required value raises at process startup, not at
first use.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment. Drives fail-fast guards for dev-only components."""

    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class SecretProviderKind(StrEnum):
    """Which `SecretProvider` adapter the composition root should wire up.

    Only ``ENV`` exists as of Phase 1A (see docs/adr/0005). ``OPENBAO`` is reserved for Phase 9
    and rejected at startup until that adapter exists, so the enum documents the target shape
    without pretending it is implemented.
    """

    ENV = "env"
    OPENBAO = "openbao"


class Settings(BaseSettings):
    """Process-wide validated configuration.

    Instantiate exactly once per process via :func:`get_settings`. Never construct this directly
    in application/domain code -- inject it (or the values derived from it) through the
    composition root.
    """

    model_config = SettingsConfigDict(
        env_prefix="FINASSIST_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.LOCAL
    service_name: str = "finassist-api"
    service_version: str = "0.1.0"

    log_level: str = "INFO"
    log_format: str = Field(default="json", pattern="^(json|console)$")

    # Binds all interfaces deliberately: this is a containerized service that must accept
    # traffic routed from outside its own network namespace.
    http_host: str = "0.0.0.0"  # noqa: S104 # nosec B104
    http_port: int = Field(default=8000, ge=1, le=65535)

    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str | None = None
    otel_console_fallback: bool = True
    """Emit spans to console instead of dropping them when no OTLP endpoint is configured.

    Useful for local development; automatically disallowed in production (see validator below)
    because it would silently mean "no real trace backend" in an environment where that matters.
    """

    secret_provider: SecretProviderKind = SecretProviderKind.ENV

    request_body_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)

    @model_validator(mode="after")
    def _validate_production_constraints(self) -> Settings:
        """Fail fast on configuration that is acceptable in dev but unsafe in production.

        This is intentionally a hard error (raised during settings construction, i.e. at process
        boot) rather than a warning, per the master instruction's "fail fast on invalid production
        configuration" requirement (docs/architecture/phase-0-assessment.md §6/§23).
        """
        if self.environment is Environment.PRODUCTION:
            if self.secret_provider is not SecretProviderKind.OPENBAO:
                raise ValueError(
                    "environment=production requires secret_provider=openbao; "
                    "the env-based dev secret provider (docs/adr/0005) must never run in "
                    "production. OpenBao adapter is implemented in Phase 9."
                )
            if self.log_format != "json":
                raise ValueError("environment=production requires log_format=json")
            if self.otel_console_fallback:
                raise ValueError(
                    "environment=production must not fall back to console trace export; "
                    "configure otel_exporter_otlp_endpoint explicitly"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton, constructing it on first call.

    Cached deliberately: settings are immutable for the lifetime of a process. Tests that need a
    different configuration should call ``get_settings.cache_clear()`` and construct ``Settings``
    with explicit overrides rather than mutating environment variables mid-process.
    """
    return Settings()
