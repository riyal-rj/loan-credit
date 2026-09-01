"""Document intelligence + cross-source verification integration tests (Phase 4, docs/adr/0012):
real PostgreSQL plus the *real* mock KYC/bureau/employer/core-banking FastAPI apps (Phase 2),
run in-process via `uvicorn.Server` on ephemeral localhost ports -- the same apps `tests/contract/`
loads by file path, here reached over a real HTTP round trip through `HttpKycVerifier`/etc.
instead of FastAPI's `TestClient`, so this actually exercises the JSON request/response contract
those adapters depend on, not just the mock services' own internal logic.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import uvicorn
from services.synthetic_data.applicants import generate_applicant
from services.synthetic_data.employer import generate_employment_record
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.application.commands.verify_application_facts import (
    VerifyApplicationFactsCommand,
    VerifyApplicationFactsHandler,
)
from finassist.application.ports.document_repository import UploadedDocument
from finassist.application.ports.id_generator import UuidIdGenerator
from finassist.domain.applications.applicant import Applicant
from finassist.domain.applications.application import Application
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.documents.document_fact import DocumentClassification, ExtractedFact, FactType
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import (
    ApplicantId,
    ApplicationId,
    ProductId,
    TenantId,
    new_id,
)
from finassist.domain.shared.money import Money
from finassist.domain.verification.contradiction import VerificationVerdict
from finassist.infrastructure.external_systems.bureau_client import HttpBureauClient
from finassist.infrastructure.external_systems.core_banking_client import HttpCoreBankingClient
from finassist.infrastructure.external_systems.employer_client import HttpEmployerVerifier
from finassist.infrastructure.external_systems.kyc_client import HttpKycVerifier
from finassist.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWorkFactory
from tests.contract.conftest import load_mock_app

from .test_application_repository import _seed_tenant_and_product

pytestmark = pytest.mark.asyncio(loop_scope="session")

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_MOCK_SERVICE_DIRS = {
    "kyc": "mock-kyc",
    "bureau": "mock-bureau",
    "employer": "mock-employer",
    "core_banking": "mock-core-banking",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def _serving_all(ports: dict[str, int]) -> AsyncIterator[None]:
    servers = []
    tasks = []
    for name, dir_name in _MOCK_SERVICE_DIRS.items():
        app = load_mock_app(dir_name)
        config = uvicorn.Config(app, host="127.0.0.1", port=ports[name], log_level="warning")
        server = uvicorn.Server(config)
        servers.append(server)
        tasks.append(asyncio.create_task(server.serve()))
    for server in servers:
        # uvicorn.Server exposes no awaitable "started" signal (just a plain bool flipped once
        # startup completes) -- a short bounded poll is the straightforward option here.
        for _ in range(200):  # 10s max per server
            if server.started:
                break
            await asyncio.sleep(0.05)  # noqa: ASYNC110
    try:
        yield
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def mock_service_urls() -> AsyncIterator[dict[str, str]]:
    ports = {name: _free_port() for name in _MOCK_SERVICE_DIRS}
    async with _serving_all(ports):
        yield {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}


async def test_kyc_and_employer_clients_round_trip_against_real_mock_services(
    mock_service_urls: dict[str, str],
) -> None:
    applicant = generate_applicant("NORMAL_ELIGIBLE", 0)
    employment = generate_employment_record(applicant, "NORMAL_ELIGIBLE", 0)

    kyc_client = HttpKycVerifier(base_url=mock_service_urls["kyc"], request_timeout_seconds=5.0)
    await kyc_client.check_connectivity()
    kyc_result = await kyc_client.verify_identity(
        given_name=applicant.given_name,
        family_name=applicant.family_name,
        date_of_birth=applicant.date_of_birth,
        synthetic_id=applicant.synthetic_id,
        street_address=applicant.street_address,
        city=applicant.city,
    )
    assert kyc_result.status == "PASS"
    assert kyc_result.date_of_birth_match is True

    employer_client = HttpEmployerVerifier(
        base_url=mock_service_urls["employer"], request_timeout_seconds=5.0
    )
    await employer_client.check_connectivity()
    employment_result = await employer_client.verify_employment(
        given_name=applicant.given_name,
        family_name=applicant.family_name,
        synthetic_id=applicant.synthetic_id,
        employer_name=applicant.employer_name,
        declared_annual_income=applicant.declared_annual_income,
    )
    assert employment_result.is_employment_confirmed is True
    assert employment_result.tenure_months == employment.tenure_months

    bureau_client = HttpBureauClient(
        base_url=mock_service_urls["bureau"], request_timeout_seconds=5.0
    )
    await bureau_client.check_connectivity()
    credit_report = await bureau_client.get_credit_report(
        given_name=applicant.given_name,
        family_name=applicant.family_name,
        date_of_birth=applicant.date_of_birth,
        synthetic_id=applicant.synthetic_id,
    )
    assert credit_report.credit_score > 0

    core_banking_client = HttpCoreBankingClient(
        base_url=mock_service_urls["core_banking"], request_timeout_seconds=5.0
    )
    await core_banking_client.check_connectivity()
    history = await core_banking_client.get_transaction_history(
        given_name=applicant.given_name,
        family_name=applicant.family_name,
        synthetic_id=applicant.synthetic_id,
        declared_annual_income=applicant.declared_annual_income,
    )
    assert history.nsf_count_last_90_days >= 0


async def test_verify_application_facts_end_to_end_against_real_postgres_and_mock_services(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
    mock_service_urls: dict[str, str],
) -> None:
    tenant_id, product_id = new_id(), new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_id, product_id=product_id
    )
    uow_factory = SqlAlchemyUnitOfWorkFactory(
        session_factory, clock=FixedClock(_NOW), id_generator=UuidIdGenerator()
    )

    applicant = generate_applicant("NORMAL_ELIGIBLE", 5)
    generate_employment_record(applicant, "NORMAL_ELIGIBLE", 5)

    def _extracted(fact_type: FactType, value: str) -> ExtractedFact:
        return ExtractedFact(
            fact_type=fact_type,
            value=value,
            normalized_value=value,
            confidence=1.0,
            page=1,
            extraction_method="regex_pattern_match",
            extractor_version="regex-v1",
            source_checksum="x",
        )

    async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
        domain_applicant = Applicant(
            applicant_id=ApplicantId(new_id()),
            tenant_id=TenantId(tenant_id),
            given_name=applicant.given_name,
            family_name=applicant.family_name,
            date_of_birth=applicant.date_of_birth,
            email="ada@example.test",
        )
        await uow.applicants.add(domain_applicant)
        product = await uow.products.get(product_id=ProductId(product_id))
        assert product is not None
        application = Application.create(
            application_id=ApplicationId(new_id()),
            tenant_id=TenantId(tenant_id),
            applicant_id=domain_applicant.applicant_id,
            product=product,
            requested_amount=Money.of("5000.00", "USD"),
            requested_term_months=24,
            clock=FixedClock(_NOW),
        )
        for step in (
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.INTAKE_VALIDATION,
            ApplicationStatus.DOCUMENT_PROCESSING,
            ApplicationStatus.VERIFICATION,
        ):
            application.transition_to(step, reason="test setup", clock=FixedClock(_NOW))
        application.pull_events()
        await uow.applications.add(application)

        await uow.documents.add(
            UploadedDocument(
                document_id="doc-1",
                tenant_id=TenantId(tenant_id),
                application_id=application.application_id,
                document_type="identity_document",
                object_key=f"applications/{application.application_id}/doc-1/id.pdf",
                checksum_sha256="x",
                size_bytes=1,
                uploaded_at=_NOW,
            )
        )

        facts = [
            _extracted(FactType.SYNTHETIC_ID, applicant.synthetic_id),
            _extracted(FactType.STREET_ADDRESS, applicant.street_address),
            _extracted(FactType.CITY, applicant.city),
            _extracted(FactType.EMPLOYER_NAME, applicant.employer_name),
            _extracted(
                FactType.GROSS_MONTHLY_INCOME, f"{applicant.declared_annual_income / 12:.2f}"
            ),
        ]
        await uow.extraction.add_run(
            run_id="run-1",
            tenant_id=TenantId(tenant_id),
            application_id=application.application_id,
            document_id="doc-1",
            classification=DocumentClassification.IDENTITY_DOCUMENT,
            facts=facts,
            fact_ids=[f"fact-{i}" for i in range(len(facts))],
            completed_at=_NOW,
        )
        await uow.commit()
        application_id = application.application_id

    handler = VerifyApplicationFactsHandler(
        uow_factory=uow_factory,
        kyc_verifier=HttpKycVerifier(
            base_url=mock_service_urls["kyc"], request_timeout_seconds=5.0
        ),
        employer_verifier=HttpEmployerVerifier(
            base_url=mock_service_urls["employer"], request_timeout_seconds=5.0
        ),
        bureau_client=HttpBureauClient(
            base_url=mock_service_urls["bureau"], request_timeout_seconds=5.0
        ),
        core_banking_client=HttpCoreBankingClient(
            base_url=mock_service_urls["core_banking"], request_timeout_seconds=5.0
        ),
        id_generator=UuidIdGenerator(),
        clock=FixedClock(_NOW),
    )
    result = await handler.handle(
        VerifyApplicationFactsCommand(
            tenant_id=TenantId(tenant_id), application_id=application_id, idempotency_key=new_id()
        )
    )

    assert result.contradiction_count == 0
    verdicts = {c.source_system.value: c.verdict for c in result.checks}
    assert verdicts["MOCK_KYC"] is VerificationVerdict.MATCHED
    assert verdicts["MOCK_EMPLOYER"] is VerificationVerdict.MATCHED

    async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
        persisted_checks = await uow.verification.get_checks_for_application(
            tenant_id=TenantId(tenant_id), application_id=application_id
        )
    assert len(persisted_checks) == len(result.checks)
