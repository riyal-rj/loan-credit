from __future__ import annotations

import pytest

from finassist.application.commands.verify_application_facts import (
    VerifyApplicationFactsCommand,
    VerifyApplicationFactsHandler,
)
from finassist.application.ports.external_verification import (
    CreditReport,
    EmploymentVerificationResult,
    KycVerificationResult,
    TransactionHistory,
)
from finassist.application.ports.extraction_repository import StoredFact
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.documents.document_fact import ExtractedFact, FactType
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import ApplicationId, TenantId, new_id
from finassist.domain.verification.contradiction import VerificationVerdict

from ._fakes import (
    FakeBureauClient,
    FakeCoreBankingClient,
    FakeEmployerVerifier,
    FakeKycVerifier,
    FakeUnitOfWorkFactory,
    FixedIdGenerator,
)
from ._helpers import NOW, make_product, seed_application_at


def _fact(fact_type: FactType, value: str) -> ExtractedFact:
    return ExtractedFact(
        fact_type=fact_type,
        value=value,
        normalized_value=value,
        confidence=1.0,
        page=1,
        extraction_method="regex_pattern_match",
        extractor_version="regex-v1",
        source_checksum="checksum",
    )


def _matching_kyc_result() -> KycVerificationResult:
    return KycVerificationResult(
        status="PASS",
        name_match_score=0.99,
        address_match_score=0.98,
        date_of_birth_match=True,
        reference_id="KYC-1",
    )


def _matching_employment_result(declared_income: int) -> EmploymentVerificationResult:
    return EmploymentVerificationResult(
        is_employment_confirmed=True, verified_annual_income=declared_income, tenure_months=24
    )


async def _seed_with_facts(
    factory: FakeUnitOfWorkFactory, tenant_id: TenantId, *, include_employment: bool = True
) -> str:
    product = make_product()
    factory.store.products[str(product.product_id)] = product
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.VERIFICATION
    )
    facts = [
        _fact(FactType.SYNTHETIC_ID, "900-11-2222"),
        _fact(FactType.STREET_ADDRESS, "123 Main St"),
        _fact(FactType.CITY, "Springfield"),
    ]
    if include_employment:
        facts.append(_fact(FactType.EMPLOYER_NAME, "Acme Inc."))
        facts.append(_fact(FactType.GROSS_MONTHLY_INCOME, "5000.00"))
    factory.store.extracted_facts.extend(
        StoredFact(fact_id=f"fact-{i}", document_id="doc-1", run_id="run-1", fact=fact)
        for i, fact in enumerate(facts)
    )
    return str(application_id)


def _handler(
    factory: FakeUnitOfWorkFactory,
    *,
    kyc_result: KycVerificationResult | None = None,
    employment_result: EmploymentVerificationResult | None = None,
) -> VerifyApplicationFactsHandler:
    return VerifyApplicationFactsHandler(
        uow_factory=factory,
        kyc_verifier=FakeKycVerifier(kyc_result or _matching_kyc_result()),
        employer_verifier=FakeEmployerVerifier(
            employment_result or _matching_employment_result(60_000)
        ),
        bureau_client=FakeBureauClient(
            CreditReport(
                credit_score=720, tradelines=[], hard_inquiries_last_12_months=1,
                is_duplicate_identity_flag=False,
            )
        ),
        core_banking_client=FakeCoreBankingClient(
            TransactionHistory(
                average_daily_balance_cents=100_000, nsf_count_last_90_days=0,
                recent_transactions=[],
            )
        ),
        id_generator=FixedIdGenerator([f"id-{i}" for i in range(20)]),
        clock=FixedClock(NOW),
    )


@pytest.mark.asyncio
async def test_all_facts_present_and_matching_produces_matched_verdicts() -> None:
    tenant_id = TenantId(new_id())
    factory = FakeUnitOfWorkFactory()
    application_id = await _seed_with_facts(factory, tenant_id)

    handler = _handler(factory)
    result = await handler.handle(
        VerifyApplicationFactsCommand(
            tenant_id=tenant_id,
            application_id=ApplicationId(application_id),
            idempotency_key="k1",
        )
    )

    assert result.contradiction_count == 0
    verdicts = {c.source_system.value: c.verdict for c in result.checks}
    assert verdicts["MOCK_KYC"] is VerificationVerdict.MATCHED
    assert verdicts["MOCK_EMPLOYER"] is VerificationVerdict.MATCHED
    assert "matched" in result.summary


@pytest.mark.asyncio
async def test_missing_identity_facts_yields_insufficient_evidence() -> None:
    tenant_id = TenantId(new_id())
    factory = FakeUnitOfWorkFactory()
    application_id = await _seed_with_facts(factory, tenant_id, include_employment=False)
    # Remove the identity facts a real "no ID uploaded" case would also lack.
    factory.store.extracted_facts.clear()

    handler = _handler(factory)
    result = await handler.handle(
        VerifyApplicationFactsCommand(
            tenant_id=tenant_id,
            application_id=ApplicationId(application_id),
            idempotency_key="k1",
        )
    )

    assert result.contradiction_count == 0
    verdicts = {c.source_system.value: c.verdict for c in result.checks}
    assert verdicts["MOCK_KYC"] is VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert verdicts["MOCK_EMPLOYER"] is VerificationVerdict.INSUFFICIENT_EVIDENCE


@pytest.mark.asyncio
async def test_employer_income_mismatch_is_contradicted() -> None:
    tenant_id = TenantId(new_id())
    factory = FakeUnitOfWorkFactory()
    application_id = await _seed_with_facts(factory, tenant_id)

    # Declared (extracted) annual income is $5000/mo * 12 = $60,000; verified is far lower.
    handler = _handler(
        factory,
        employment_result=EmploymentVerificationResult(
            is_employment_confirmed=True, verified_annual_income=20_000, tenure_months=3
        ),
    )
    result = await handler.handle(
        VerifyApplicationFactsCommand(
            tenant_id=tenant_id,
            application_id=ApplicationId(application_id),
            idempotency_key="k1",
        )
    )

    assert result.contradiction_count == 1
    verdicts = {c.source_system.value: c.verdict for c in result.checks}
    assert verdicts["MOCK_EMPLOYER"] is VerificationVerdict.CONTRADICTED
    assert "MOCK_EMPLOYER" in result.summary


@pytest.mark.asyncio
async def test_kyc_failure_is_contradicted() -> None:
    tenant_id = TenantId(new_id())
    factory = FakeUnitOfWorkFactory()
    application_id = await _seed_with_facts(factory, tenant_id)

    handler = _handler(
        factory,
        kyc_result=KycVerificationResult(
            status="FAIL", name_match_score=0.3, address_match_score=0.2,
            date_of_birth_match=False, reference_id="KYC-2",
        ),
    )
    result = await handler.handle(
        VerifyApplicationFactsCommand(
            tenant_id=tenant_id,
            application_id=ApplicationId(application_id),
            idempotency_key="k1",
        )
    )

    assert result.contradiction_count == 1
    verdicts = {c.source_system.value: c.verdict for c in result.checks}
    assert verdicts["MOCK_KYC"] is VerificationVerdict.CONTRADICTED
