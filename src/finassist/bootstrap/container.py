"""Composition root: wires concrete adapters into ports and owns process lifecycle.

No other module is allowed to instantiate a concrete infrastructure/security adapter directly --
everything downstream (API routes, application services) receives already-wired dependencies from
here, via FastAPI's dependency-injection system for the API process and via an equivalent explicit
wiring call for the worker process. This keeps `docs/adr/0001`'s dependency-direction rule real
rather than aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry.sdk.trace import TracerProvider

from finassist.bootstrap.logging import configure_logging, get_logger
from finassist.bootstrap.settings import Environment, SecretProviderKind, Settings, get_settings
from finassist.bootstrap.telemetry import configure_telemetry, shutdown_telemetry
from finassist.security.env_secret_provider import EnvSecretProvider
from finassist.security.ports import AuthorizationProvider, SecretProvider


class UnsupportedProviderConfigurationError(RuntimeError):
    """Raised when the composition root cannot build a valid adapter for the requested config.

    This is the enforcement point for docs/adr/0005: it is impossible to end up with a
    dev-only security adapter wired into a process configured as ``Environment.PRODUCTION``,
    because that combination never reaches here (rejected earlier by `Settings` validation) and
    because no production-grade adapter exists yet to build in its place.
    """


@dataclass(slots=True)
class Container:
    """Holds the fully-wired dependencies for one process lifetime."""

    settings: Settings
    secret_provider: SecretProvider
    authorization_provider: AuthorizationProvider
    tracer_provider: TracerProvider


def _build_secret_provider(settings: Settings) -> SecretProvider:
    if settings.secret_provider is SecretProviderKind.ENV:
        return EnvSecretProvider()
    raise UnsupportedProviderConfigurationError(
        f"secret_provider={settings.secret_provider.value!r} has no adapter yet "
        "(OpenBao adapter lands in Phase 9; see docs/adr/0005)"
    )


def _build_authorization_provider(settings: Settings) -> AuthorizationProvider:
    if settings.environment is Environment.PRODUCTION:
        # Unreachable today because Settings rejects environment=production outright (it
        # requires secret_provider=openbao, which has no adapter yet and raises above first).
        # Kept as an explicit, named failure rather than silently falling through to the dev
        # stub, so a future change to the settings validator can't accidentally re-open this gap.
        raise UnsupportedProviderConfigurationError(
            "no production-grade AuthorizationProvider exists yet (OPA integration lands in "
            "Phase 9); refusing to start with a dev stub under environment=production"
        )
    from finassist.security.dev_auth import AllowAllAuthorizationProvider

    return AllowAllAuthorizationProvider()


def build_container(settings: Settings | None = None) -> Container:
    """Construct the fully-wired :class:`Container` for this process.

    Call once at process startup (API and worker each call this independently). Configures
    logging and telemetry as a side effect, because both must be active before any other code
    in the process runs.
    """
    resolved_settings = settings or get_settings()

    configure_logging(resolved_settings)
    tracer_provider = configure_telemetry(resolved_settings)

    logger = get_logger(__name__)
    logger.info(
        "container.build.start",
        environment=resolved_settings.environment.value,
        service=resolved_settings.service_name,
    )

    secret_provider = _build_secret_provider(resolved_settings)
    authorization_provider = _build_authorization_provider(resolved_settings)

    container = Container(
        settings=resolved_settings,
        secret_provider=secret_provider,
        authorization_provider=authorization_provider,
        tracer_provider=tracer_provider,
    )

    logger.info("container.build.complete")
    return container


def shutdown_container(container: Container) -> None:
    """Release process-wide resources held by ``container``. Call during graceful shutdown."""
    logger = get_logger(__name__)
    logger.info("container.shutdown.start")
    shutdown_telemetry()
    logger.info("container.shutdown.complete")
