"""Composition root: wires concrete adapters into ports and owns process lifecycle.

No other module is allowed to instantiate a concrete infrastructure/security adapter directly --
everything downstream (API routes, application services) receives already-wired dependencies from
here, via FastAPI's dependency-injection system for the API process and via an equivalent explicit
wiring call for the worker process. This keeps `docs/adr/0001`'s dependency-direction rule real
rather than aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass

import aioboto3
from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finassist.application.ports.document_extractor import DocumentExtractor
from finassist.application.ports.document_parser import DocumentParser
from finassist.application.ports.external_verification import (
    BureauClient,
    CoreBankingClient,
    EmployerVerifier,
    KycVerifier,
)
from finassist.application.ports.file_safety import FileSafetyScanner
from finassist.application.ports.id_generator import IdGenerator, UuidIdGenerator
from finassist.application.ports.object_store import ObjectStore
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.application.ports.workflow_runner import WorkflowRunner
from finassist.bootstrap.logging import configure_logging, get_logger
from finassist.bootstrap.settings import Environment, SecretProviderKind, Settings, get_settings
from finassist.bootstrap.telemetry import configure_telemetry, shutdown_telemetry
from finassist.domain.shared.clock import Clock, SystemClock
from finassist.infrastructure.documents.file_safety_scanner import StubFileSafetyScanner
from finassist.infrastructure.documents.pdf_parser import PyPdfDocumentParser
from finassist.infrastructure.documents.regex_extractor import RegexDocumentExtractor
from finassist.infrastructure.external_systems.bureau_client import HttpBureauClient
from finassist.infrastructure.external_systems.core_banking_client import HttpCoreBankingClient
from finassist.infrastructure.external_systems.employer_client import HttpEmployerVerifier
from finassist.infrastructure.external_systems.kyc_client import HttpKycVerifier
from finassist.infrastructure.object_store.minio_client import S3ObjectStore
from finassist.infrastructure.postgres.database import build_engine, build_session_factory
from finassist.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWorkFactory
from finassist.infrastructure.temporal.client import TemporalWorkflowRunner
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
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    clock: Clock
    id_generator: IdGenerator
    uow_factory: UnitOfWorkFactory
    object_store: ObjectStore
    workflow_runner: WorkflowRunner
    file_safety_scanner: FileSafetyScanner
    document_parser: DocumentParser
    document_extractor: DocumentExtractor
    kyc_verifier: KycVerifier
    employer_verifier: EmployerVerifier
    bureau_client: BureauClient
    core_banking_client: CoreBankingClient


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

    engine = build_engine(resolved_settings)
    session_factory = build_session_factory(engine)
    clock = SystemClock()
    id_generator = UuidIdGenerator()
    uow_factory = SqlAlchemyUnitOfWorkFactory(
        session_factory, clock=clock, id_generator=id_generator
    )
    object_store = S3ObjectStore(
        aioboto3.Session(
            aws_access_key_id=resolved_settings.object_store_access_key,
            aws_secret_access_key=resolved_settings.object_store_secret_key,
        ),
        endpoint_url=resolved_settings.object_store_endpoint_url,
        bucket=resolved_settings.object_store_bucket,
        use_ssl=resolved_settings.object_store_use_ssl,
        request_timeout_seconds=resolved_settings.object_store_request_timeout_seconds,
    )
    workflow_runner = TemporalWorkflowRunner(
        target_host=f"{resolved_settings.temporal_host}:{resolved_settings.temporal_port}",
        namespace=resolved_settings.temporal_namespace,
        task_queue=resolved_settings.temporal_task_queue,
        tls=resolved_settings.temporal_tls_enabled,
        human_review_sla_seconds=resolved_settings.temporal_human_review_sla_seconds,
    )
    file_safety_scanner = StubFileSafetyScanner(
        max_size_bytes=resolved_settings.document_max_size_bytes,
        max_pages=resolved_settings.document_max_pages,
    )
    document_parser = PyPdfDocumentParser()
    document_extractor = RegexDocumentExtractor()
    kyc_verifier = HttpKycVerifier(
        base_url=resolved_settings.mock_kyc_base_url,
        request_timeout_seconds=resolved_settings.document_request_timeout_seconds,
    )
    employer_verifier = HttpEmployerVerifier(
        base_url=resolved_settings.mock_employer_base_url,
        request_timeout_seconds=resolved_settings.document_request_timeout_seconds,
    )
    bureau_client = HttpBureauClient(
        base_url=resolved_settings.mock_bureau_base_url,
        request_timeout_seconds=resolved_settings.document_request_timeout_seconds,
    )
    core_banking_client = HttpCoreBankingClient(
        base_url=resolved_settings.mock_core_banking_base_url,
        request_timeout_seconds=resolved_settings.document_request_timeout_seconds,
    )

    container = Container(
        settings=resolved_settings,
        secret_provider=secret_provider,
        authorization_provider=authorization_provider,
        tracer_provider=tracer_provider,
        engine=engine,
        session_factory=session_factory,
        clock=clock,
        id_generator=id_generator,
        uow_factory=uow_factory,
        object_store=object_store,
        workflow_runner=workflow_runner,
        file_safety_scanner=file_safety_scanner,
        document_parser=document_parser,
        document_extractor=document_extractor,
        kyc_verifier=kyc_verifier,
        employer_verifier=employer_verifier,
        bureau_client=bureau_client,
        core_banking_client=core_banking_client,
    )

    logger.info("container.build.complete")
    return container


async def shutdown_container(container: Container) -> None:
    """Release process-wide resources held by ``container``. Call during graceful shutdown."""
    logger = get_logger(__name__)
    logger.info("container.shutdown.start")
    await container.engine.dispose()
    shutdown_telemetry()
    logger.info("container.shutdown.complete")
