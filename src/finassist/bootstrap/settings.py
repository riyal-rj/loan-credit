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


_DEFAULT_LOCAL_DATABASE_URL = (
    "postgresql+asyncpg://finassist_app:finassist_app@localhost:5433/finassist"
)
_DEFAULT_LOCAL_MIGRATION_DATABASE_URL = (
    "postgresql+asyncpg://finassist:finassist@localhost:5433/finassist"
)
_DEFAULT_LOCAL_OBJECT_STORE_SECRET_KEY = "finassist_minio_secret"  # noqa: S105 # nosec B105


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

    # Local-dev-only default credential (docker compose's postgres service uses the same value).
    # Never a real secret: Phase 9 replaces this with OpenBao-issued dynamic credentials injected
    # at deploy time (docs/adr/0009), at which point this default is removed, not overridden.
    #
    # `database_url` is the low-privilege, non-superuser role the *application* connects as --
    # required for row-level security to apply at all (PostgreSQL exempts superusers from RLS
    # even with FORCE ROW LEVEL SECURITY, which this project's own integration tests caught; see
    # docs/adr/0009 and docs/architecture/phase-1b-completion.md). `database_migration_url` is the
    # separate, more-privileged role Alembic uses to run DDL; it defaults to the same value as
    # `database_url` only when both are left unset in an environment that has no such distinction
    # (never true for local/staging/production, which always set both explicitly).
    database_url: str = _DEFAULT_LOCAL_DATABASE_URL
    database_migration_url: str = _DEFAULT_LOCAL_MIGRATION_DATABASE_URL
    database_pool_min_size: int = Field(default=1, ge=1)
    database_pool_max_size: int = Field(default=10, ge=1)
    database_statement_timeout_seconds: float = Field(default=10.0, gt=0)

    # Local-dev-only default (docker compose's minio service uses the same values). Phase 9
    # replaces the static access/secret key pair with OpenBao-issued credentials, same pattern as
    # the database settings above.
    object_store_endpoint_url: str = "http://localhost:9000"
    object_store_access_key: str = "finassist"
    object_store_secret_key: str = _DEFAULT_LOCAL_OBJECT_STORE_SECRET_KEY
    object_store_bucket: str = "finassist-documents"
    object_store_use_ssl: bool = False
    object_store_request_timeout_seconds: float = Field(default=5.0, gt=0)

    # Local-dev-only defaults matching compose.yaml's `temporal` service (docs/adr/0011): a
    # single-binary `temporal server start-dev` instance, no TLS, no persistent store. Phase 9/10
    # replaces this with a real persistent-store cluster; `temporal_tls_enabled` exists now so the
    # production-safety validator below has something real to check rather than being added later
    # as an afterthought.
    temporal_host: str = "localhost"
    temporal_port: int = Field(default=7233, ge=1, le=65535)
    temporal_namespace: str = "default"
    temporal_task_queue: str = "finassist-applications"
    temporal_tls_enabled: bool = False
    temporal_human_review_sla_seconds: float = Field(default=30 * 24 * 60 * 60, gt=0)
    """Durable timer duration for `AWAITING_HUMAN_REVIEW` before the workflow auto-escalates
    (docs/adr/0002 "durable timers for ... escalation"). 30 days by default; tests override this
    per-workflow-input rather than changing process-wide settings."""

    # Local-dev-only defaults matching compose.yaml's `kafka` service (single-broker KRaft mode,
    # no auth). docs/adr/0011: Apicurio schema registry is deferred past this phase.
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_applications_topic: str = "finassist.applications.events"
    kafka_security_protocol: str = Field(default="PLAINTEXT", pattern="^(PLAINTEXT|SSL)$")
    kafka_outbox_relay_poll_interval_seconds: float = Field(default=2.0, gt=0)
    kafka_outbox_relay_batch_size: int = Field(default=100, ge=1)
    kafka_projection_consumer_group: str = "applications-projection"

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
            if self.database_url == _DEFAULT_LOCAL_DATABASE_URL:
                raise ValueError(
                    "environment=production must not use the local-dev default database_url"
                )
            if self.database_migration_url == _DEFAULT_LOCAL_MIGRATION_DATABASE_URL:
                raise ValueError(
                    "environment=production must not use the local-dev default "
                    "database_migration_url"
                )
            if self.object_store_secret_key == _DEFAULT_LOCAL_OBJECT_STORE_SECRET_KEY:
                raise ValueError(
                    "environment=production must not use the local-dev default "
                    "object_store_secret_key"
                )
            if not self.temporal_tls_enabled:
                raise ValueError(
                    "environment=production requires temporal_tls_enabled=true; the dev-mode "
                    "Temporal server (docs/adr/0011) has no TLS and must never be reachable "
                    "from a production process"
                )
            if self.kafka_security_protocol == "PLAINTEXT":
                raise ValueError(
                    "environment=production must not use kafka_security_protocol=PLAINTEXT"
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
