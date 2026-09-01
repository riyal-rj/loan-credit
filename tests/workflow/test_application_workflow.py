"""`ApplicationWorkflow` replay/behavior tests (master instruction §13/§21.1: "test workflow
replay", "signal, retries, versioning" tests).

Uses `temporalio.testing.WorkflowEnvironment`'s time-skipping test server -- a real (but
ephemeral, in-process) Temporal server, so this exercises the actual workflow determinism/replay
machinery, not a hand-rolled simulation. `ApplicationActivities` runs for real against a
`FakeUnitOfWorkFactory` and fake object-store/external-verification adapters (the same fakes the
command-handler unit tests use), so this layer tests the *workflow's control flow* -- which
activity runs when, what a signal/timeout does -- while application-layer correctness is already
covered by `tests/unit/application/commands/test_advance_*.py`/`test_process_document.py`/
`test_verify_application_facts.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from services.synthetic_data.applicants import generate_applicant
from services.synthetic_data.documents import generate_pay_stub_pdf
from services.synthetic_data.employer import generate_employment_record
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from finassist.application.ports.document_repository import UploadedDocument
from finassist.application.ports.external_verification import (
    CreditReport,
    EmploymentVerificationResult,
    KycVerificationResult,
    TransactionHistory,
)
from finassist.application.ports.id_generator import UuidIdGenerator
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import SystemClock
from finassist.domain.shared.identifiers import ApplicationId, TenantId, new_id
from finassist.infrastructure.documents.pdf_parser import PyPdfDocumentParser
from finassist.infrastructure.documents.regex_extractor import RegexDocumentExtractor
from finassist.infrastructure.temporal.activities import ApplicationActivities
from finassist.infrastructure.temporal.workflows import (
    ApplicationWorkflow,
    ApplicationWorkflowInput,
    ReviewDecisionSignal,
)
from tests.unit.application.commands._fakes import (
    FakeBureauClient,
    FakeCoreBankingClient,
    FakeEmployerVerifier,
    FakeKycVerifier,
    FakeObjectStore,
    FakeUnitOfWorkFactory,
)
from tests.unit.application.commands._helpers import make_product, seed_application_at

_SHORT_SLA_SECONDS = 30.0

_MATCHED_KYC_RESULT = KycVerificationResult(
    status="PASS",
    name_match_score=0.99,
    address_match_score=0.98,
    date_of_birth_match=True,
    reference_id="KYC-1",
)
_MATCHED_EMPLOYMENT_RESULT = EmploymentVerificationResult(
    is_employment_confirmed=True, verified_annual_income=60_000, tenure_months=24
)
_EMPTY_CREDIT_REPORT = CreditReport(
    credit_score=700, tradelines=[], hard_inquiries_last_12_months=0,
    is_duplicate_identity_flag=False,
)
_EMPTY_TRANSACTION_HISTORY = TransactionHistory(
    average_daily_balance_cents=50_000, nsf_count_last_90_days=0, recent_transactions=[]
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def time_skipping_env() -> AsyncIterator[WorkflowEnvironment]:
    env = await WorkflowEnvironment.start_time_skipping()
    yield env
    await env.shutdown()


async def _run_workflow(
    env: WorkflowEnvironment,
    *,
    starting_status: ApplicationStatus,
    tenant_id: TenantId,
    application_id: ApplicationId,
    version: int,
    factory: FakeUnitOfWorkFactory,
    signal: ReviewDecisionSignal | None,
    sla_seconds: float = _SHORT_SLA_SECONDS,
    object_store: FakeObjectStore | None = None,
) -> ApplicationStatus:
    activities = ApplicationActivities(
        uow_factory=factory,
        clock=SystemClock(),
        id_generator=UuidIdGenerator(),
        object_store=object_store or FakeObjectStore(),
        document_parser=PyPdfDocumentParser(),
        document_extractor=RegexDocumentExtractor(),
        kyc_verifier=FakeKycVerifier(_MATCHED_KYC_RESULT),
        employer_verifier=FakeEmployerVerifier(_MATCHED_EMPLOYMENT_RESULT),
        bureau_client=FakeBureauClient(_EMPTY_CREDIT_REPORT),
        core_banking_client=FakeCoreBankingClient(_EMPTY_TRANSACTION_HISTORY),
    )
    task_queue = f"tq-{uuid4()}"
    workflow_id = f"application:{tenant_id}:{application_id}:v{version}"

    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[ApplicationWorkflow],
        activities=[
            activities.validate_intake_activity,
            activities.check_required_documents_activity,
            activities.extract_document_facts_activity,
            activities.verify_facts_activity,
            activities.enter_human_review_activity,
            activities.apply_review_decision_activity,
        ],
    ):
        handle = await env.client.start_workflow(
            ApplicationWorkflow.run,
            ApplicationWorkflowInput(
                tenant_id=str(tenant_id),
                application_id=str(application_id),
                version=version,
                starting_status=starting_status.value,
                human_review_sla_seconds=sla_seconds,
            ),
            id=workflow_id,
            task_queue=task_queue,
        )
        if signal is not None:
            await handle.signal(ApplicationWorkflow.submit_review_decision, signal)
        result = await handle.result()
        return ApplicationStatus(result.final_status)


@pytest.mark.asyncio(loop_scope="session")
async def test_golden_path_reaches_human_review_then_approved(
    time_skipping_env: WorkflowEnvironment,
) -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.SUBMITTED
    )
    # Upload happens out-of-band of the workflow in real usage (via the API); here we seed a real
    # synthetic pay stub -- extract_document_facts_activity actually parses it.
    object_store = FakeObjectStore()
    applicant = generate_applicant("NORMAL_ELIGIBLE", 0)
    employment = generate_employment_record(applicant, "NORMAL_ELIGIBLE", 0)
    pdf_bytes = generate_pay_stub_pdf(applicant, employment)
    document_id = new_id()
    object_key = f"applications/{application_id}/{document_id}/paystub.pdf"
    await object_store.put_object(
        tenant_id=tenant_id, key=object_key, data=pdf_bytes, content_type="application/pdf"
    )
    factory.store.documents.append(
        UploadedDocument(
            document_id=document_id,
            tenant_id=tenant_id,
            application_id=application_id,
            document_type="income_proof",
            object_key=object_key,
            checksum_sha256="irrelevant-for-this-test",
            size_bytes=len(pdf_bytes),
            uploaded_at=datetime.now(UTC),
        )
    )

    final_status = await _run_workflow(
        time_skipping_env,
        starting_status=ApplicationStatus.SUBMITTED,
        tenant_id=tenant_id,
        application_id=application_id,
        version=2,
        factory=factory,
        object_store=object_store,
        signal=ReviewDecisionSignal(
            decision=ApplicationStatus.APPROVED.value, reason="looks good", reviewer_id="rev-1"
        ),
    )

    assert final_status is ApplicationStatus.APPROVED
    entry = factory.store.review_queue_entries[(str(tenant_id), str(application_id))]
    assert entry.decision == "APPROVED"
    assert len(factory.store.extracted_facts) > 0
    checks = factory.store.verification_checks[(str(tenant_id), str(application_id))]
    assert any(c.source_system.value == "MOCK_EMPLOYER" for c in checks)


@pytest.mark.asyncio(loop_scope="session")
async def test_out_of_bounds_intake_escalates_then_declined(
    time_skipping_env: WorkflowEnvironment,
) -> None:
    tenant_id = TenantId(new_id())
    product = make_product(min_amount="1000.00", max_amount="2000.00")
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory,
        tenant_id=tenant_id,
        product=product,
        status=ApplicationStatus.SUBMITTED,
        requested_amount="5000.00",
    )

    final_status = await _run_workflow(
        time_skipping_env,
        starting_status=ApplicationStatus.SUBMITTED,
        tenant_id=tenant_id,
        application_id=application_id,
        version=2,
        factory=factory,
        signal=ReviewDecisionSignal(
            decision=ApplicationStatus.DECLINED.value,
            reason="out of policy bounds",
            reviewer_id="rev-1",
        ),
    )

    assert final_status is ApplicationStatus.DECLINED
    # check_required_documents_activity must never have run: intake already reached
    # AWAITING_HUMAN_REVIEW, so no review-queue entry duplication/second escalation happened.
    # Seeded at SUBMITTED = version 2; +3 hops (INTAKE_VALIDATION, AWAITING_HUMAN_REVIEW,
    # DECLINED) = version 5.
    saved = factory.store.applications[(str(tenant_id), str(application_id))]
    assert saved.version == 5


@pytest.mark.asyncio(loop_scope="session")
async def test_zero_documents_escalates_then_needs_more_information(
    time_skipping_env: WorkflowEnvironment,
) -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.SUBMITTED
    )

    final_status = await _run_workflow(
        time_skipping_env,
        starting_status=ApplicationStatus.SUBMITTED,
        tenant_id=tenant_id,
        application_id=application_id,
        version=2,
        factory=factory,
        signal=ReviewDecisionSignal(
            decision=ApplicationStatus.NEEDS_MORE_INFORMATION.value,
            reason="missing income proof",
            reviewer_id="rev-1",
        ),
    )

    assert final_status is ApplicationStatus.NEEDS_MORE_INFORMATION


@pytest.mark.asyncio(loop_scope="session")
async def test_resubmission_entry_point_skips_intake_validation(
    time_skipping_env: WorkflowEnvironment,
) -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory,
        tenant_id=tenant_id,
        product=product,
        status=ApplicationStatus.DOCUMENT_PROCESSING,
    )

    final_status = await _run_workflow(
        time_skipping_env,
        starting_status=ApplicationStatus.DOCUMENT_PROCESSING,
        tenant_id=tenant_id,
        application_id=application_id,
        version=4,
        factory=factory,
        signal=ReviewDecisionSignal(
            decision=ApplicationStatus.APPROVED.value, reason="ok", reviewer_id="rev-1"
        ),
    )

    assert final_status is ApplicationStatus.APPROVED
    saved = factory.store.applications[(str(tenant_id), str(application_id))]
    # DOCUMENT_PROCESSING -> AWAITING_HUMAN_REVIEW (no docs) -> APPROVED: two hops, not the four a
    # SUBMITTED-entry run would take -- proves intake validation never ran a second time.
    assert saved.version == 6


@pytest.mark.asyncio(loop_scope="session")
async def test_sla_timeout_auto_escalates(time_skipping_env: WorkflowEnvironment) -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.SUBMITTED
    )

    final_status = await _run_workflow(
        time_skipping_env,
        starting_status=ApplicationStatus.SUBMITTED,
        tenant_id=tenant_id,
        application_id=application_id,
        version=2,
        factory=factory,
        signal=None,  # no reviewer ever responds -- the time-skipping server fast-forwards
        sla_seconds=timedelta(days=1).total_seconds(),
    )

    assert final_status is ApplicationStatus.ESCALATED
    entry = factory.store.review_queue_entries[(str(tenant_id), str(application_id))]
    assert entry.reviewer_id is None
