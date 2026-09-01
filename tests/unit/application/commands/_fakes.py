"""In-memory fakes for the application-layer ports, used to unit-test command handlers without a
real database. Each fake enforces the same semantics the real Postgres-backed adapter promises
(tenant scoping, idempotency-key reservation, optimistic concurrency) so a test written against
the fake stays meaningful.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import TracebackType

from finassist.application.ports.applicant_repository import ApplicantRepository
from finassist.application.ports.application_repository import ApplicationRepository
from finassist.application.ports.document_repository import DocumentRepository, UploadedDocument
from finassist.application.ports.external_verification import (
    BureauClient,
    CoreBankingClient,
    CreditReport,
    EmployerVerifier,
    EmploymentVerificationResult,
    KycVerificationResult,
    KycVerifier,
    TransactionHistory,
)
from finassist.application.ports.extraction_repository import ExtractionRepository, StoredFact
from finassist.application.ports.file_safety import FileSafetyReport, FileSafetyScanner
from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.object_store import ObjectMetadata, ObjectStore
from finassist.application.ports.product_catalog import ProductCatalog
from finassist.application.ports.review_queue_repository import (
    ReviewQueueEntry,
    ReviewQueueRepository,
)
from finassist.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from finassist.application.ports.verification_repository import (
    ExternalResponseSnapshot,
    VerificationRepository,
)
from finassist.application.ports.workflow_runner import WorkflowRunner
from finassist.domain.applications.applicant import Applicant
from finassist.domain.applications.application import Application
from finassist.domain.applications.events import DomainEvent
from finassist.domain.applications.exceptions import ConcurrencyConflictError
from finassist.domain.applications.product import Product
from finassist.domain.documents.document_fact import DocumentClassification, ExtractedFact
from finassist.domain.shared.identifiers import ApplicantId, ApplicationId, ProductId, TenantId
from finassist.domain.verification.contradiction import VerificationCheck


@dataclass
class FakeBackingStore:
    """Shared state across fake unit-of-work instances, simulating a database across
    transactions within one test."""

    applications: dict[tuple[str, str], Application] = field(default_factory=dict)
    applicants: dict[tuple[str, str], Applicant] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)
    documents: list[UploadedDocument] = field(default_factory=list)
    review_queue_entries: dict[tuple[str, str], ReviewQueueEntry] = field(default_factory=dict)
    extracted_facts: list[StoredFact] = field(default_factory=list)
    verification_checks: dict[tuple[str, str], list[VerificationCheck]] = field(
        default_factory=dict
    )
    reserved_idempotency_keys: set[tuple[str, str, str]] = field(default_factory=set)
    recorded_events: list[DomainEvent] = field(default_factory=list)


class FakeApplicationRepository(ApplicationRepository):
    def __init__(self, store: FakeBackingStore) -> None:
        self._store = store

    async def get(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> Application | None:
        # A real repository deserializes a fresh object per call; deep-copy here so mutating the
        # returned aggregate can't retroactively change what "was already saved" underneath a
        # concurrency check, the way a shared in-memory reference would.
        stored = self._store.applications.get((str(tenant_id), str(application_id)))
        return copy.deepcopy(stored) if stored is not None else None

    async def add(self, application: Application) -> None:
        key = (str(application.tenant_id), str(application.application_id))
        if key in self._store.applications:
            raise ValueError(f"application {application.application_id} already exists")
        self._store.applications[key] = copy.deepcopy(application)

    async def save(self, application: Application) -> None:
        key = (str(application.tenant_id), str(application.application_id))
        existing = self._store.applications.get(key)
        expected_prior_version = application.version - 1
        if existing is not None and existing.version != expected_prior_version:
            raise ConcurrencyConflictError(
                str(application.application_id), expected_prior_version, existing.version
            )
        self._store.applications[key] = copy.deepcopy(application)


class FakeApplicantRepository(ApplicantRepository):
    def __init__(self, store: FakeBackingStore) -> None:
        self._store = store

    async def add(self, applicant: Applicant) -> None:
        self._store.applicants[(str(applicant.tenant_id), str(applicant.applicant_id))] = applicant

    async def get(self, *, tenant_id: TenantId, applicant_id: ApplicantId) -> Applicant | None:
        return self._store.applicants.get((str(tenant_id), str(applicant_id)))


class FakeProductCatalog(ProductCatalog):
    def __init__(self, store: FakeBackingStore) -> None:
        self._store = store

    async def get(self, *, product_id: ProductId) -> Product | None:
        return self._store.products.get(str(product_id))

    async def get_by_code(self, *, code: str) -> Product | None:
        return next((p for p in self._store.products.values() if p.code == code), None)


class FakeDocumentRepository(DocumentRepository):
    def __init__(self, store: FakeBackingStore) -> None:
        self._store = store

    async def add(self, document: UploadedDocument) -> None:
        self._store.documents.append(document)

    async def count_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> int:
        documents = await self.list_for_application(
            tenant_id=tenant_id, application_id=application_id
        )
        return len(documents)

    async def list_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> list[UploadedDocument]:
        return [
            document
            for document in self._store.documents
            if document.tenant_id == tenant_id and document.application_id == application_id
        ]


class FakeReviewQueueRepository(ReviewQueueRepository):
    def __init__(self, store: FakeBackingStore) -> None:
        self._store = store

    async def add(self, entry: ReviewQueueEntry) -> None:
        self._store.review_queue_entries[(str(entry.tenant_id), str(entry.application_id))] = (
            entry
        )

    async def get(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> ReviewQueueEntry | None:
        return self._store.review_queue_entries.get((str(tenant_id), str(application_id)))

    async def mark_decided(
        self,
        *,
        tenant_id: TenantId,
        application_id: ApplicationId,
        decision: str,
        reason: str,
        reviewer_id: str | None,
        decided_at: datetime,
    ) -> None:
        key = (str(tenant_id), str(application_id))
        existing = self._store.review_queue_entries.get(key)
        if existing is None:
            raise LookupError(f"no review queue entry for application {application_id}")
        self._store.review_queue_entries[key] = ReviewQueueEntry(
            application_id=existing.application_id,
            tenant_id=existing.tenant_id,
            entered_queue_at=existing.entered_queue_at,
            status="decided",
            decision=decision,
            reason=reason,
            reviewer_id=reviewer_id,
            decided_at=decided_at,
        )


class FakeExtractionRepository(ExtractionRepository):
    def __init__(self, store: FakeBackingStore) -> None:
        self._store = store

    async def add_run(
        self,
        *,
        run_id: str,
        tenant_id: TenantId,
        application_id: ApplicationId,
        document_id: str,
        classification: DocumentClassification,
        facts: list[ExtractedFact],
        fact_ids: list[str],
        completed_at: datetime,
    ) -> None:
        for fact_id, fact in zip(fact_ids, facts, strict=True):
            self._store.extracted_facts.append(
                StoredFact(fact_id=fact_id, document_id=document_id, run_id=run_id, fact=fact)
            )

    async def get_facts_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> list[StoredFact]:
        return list(self._store.extracted_facts)


class FakeVerificationRepository(VerificationRepository):
    def __init__(self, store: FakeBackingStore) -> None:
        self._store = store

    async def add_run(
        self,
        *,
        run_id: str,
        tenant_id: TenantId,
        application_id: ApplicationId,
        checks: list[VerificationCheck],
        check_ids: list[str],
        snapshots: list[ExternalResponseSnapshot],
        snapshot_ids: list[str],
        completed_at: datetime,
    ) -> None:
        key = (str(tenant_id), str(application_id))
        self._store.verification_checks.setdefault(key, []).extend(checks)

    async def get_checks_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> list[VerificationCheck]:
        return list(self._store.verification_checks.get((str(tenant_id), str(application_id)), []))


class FakeUnitOfWork(UnitOfWork):
    def __init__(self, store: FakeBackingStore, tenant_id: TenantId) -> None:
        self._store = store
        self._tenant_id = tenant_id
        self.applications = FakeApplicationRepository(store)
        self.applicants = FakeApplicantRepository(store)
        self.products = FakeProductCatalog(store)
        self.documents = FakeDocumentRepository(store)
        self.review_queue = FakeReviewQueueRepository(store)
        self.extraction = FakeExtractionRepository(store)
        self.verification = FakeVerificationRepository(store)
        self.committed = False

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.committed = False

    async def record_domain_events(self, events: list[DomainEvent]) -> None:
        self._store.recorded_events.extend(events)

    async def reserve_idempotency_key(self, *, key: str, operation_name: str) -> bool:
        reservation = (str(self._tenant_id), operation_name, key)
        if reservation in self._store.reserved_idempotency_keys:
            return False
        self._store.reserved_idempotency_keys.add(reservation)
        return True


class FakeUnitOfWorkFactory(UnitOfWorkFactory):
    def __init__(
        self, store: FakeBackingStore | None = None, *, products: list[Product] | None = None
    ) -> None:
        self.store = store or FakeBackingStore()
        for product in products or []:
            self.store.products[str(product.product_id)] = product

    def begin(self, *, tenant_id: TenantId) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.store, tenant_id)


class FixedIdGenerator(IdGenerator):
    def __init__(self, ids: list[str]) -> None:
        self._ids = iter(ids)

    def new_id(self) -> str:
        return next(self._ids)


class FakeObjectStore(ObjectStore):
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self._content_types: dict[tuple[str, str], str] = {}

    async def ensure_ready(self) -> None:
        return None

    async def check_connectivity(self) -> None:
        return None

    async def put_object(
        self, *, tenant_id: TenantId, key: str, data: bytes, content_type: str
    ) -> ObjectMetadata:
        self.objects[(str(tenant_id), key)] = data
        self._content_types[(str(tenant_id), key)] = content_type
        return ObjectMetadata(
            key=key,
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type=content_type,
            version_id="1",
            uploaded_at=datetime.now(UTC),
        )

    async def get_object(self, *, tenant_id: TenantId, key: str) -> bytes:
        return self.objects[(str(tenant_id), key)]

    async def get_object_metadata(self, *, tenant_id: TenantId, key: str) -> ObjectMetadata:
        data = self.objects[(str(tenant_id), key)]
        content_type = self._content_types.get((str(tenant_id), key), "application/octet-stream")
        return ObjectMetadata(
            key=key,
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type=content_type,
            version_id="1",
            uploaded_at=datetime.now(UTC),
        )

    async def generate_presigned_get_url(
        self, *, tenant_id: TenantId, key: str, expires_in_seconds: int
    ) -> str:
        return f"https://fake-object-store.test/{tenant_id}/{key}"


@dataclass
class StartedWorkflow:
    workflow_id: str
    tenant_id: TenantId
    application_id: ApplicationId
    version: int
    starting_status: str


@dataclass
class SentSignal:
    workflow_id: str
    decision: str
    reason: str
    reviewer_id: str


class FakeWorkflowRunner(WorkflowRunner):
    """Records calls instead of talking to Temporal. `fail_on_start`/`fail_on_signal` let a test
    simulate the best-effort call failing without the surrounding command failing."""

    def __init__(self, *, fail_on_start: bool = False, fail_on_signal: bool = False) -> None:
        self.started: list[StartedWorkflow] = []
        self.signaled: list[SentSignal] = []
        self._fail_on_start = fail_on_start
        self._fail_on_signal = fail_on_signal

    async def ensure_ready(self) -> None:
        return None

    async def check_connectivity(self) -> None:
        return None

    async def start_application_workflow(
        self,
        *,
        workflow_id: str,
        tenant_id: TenantId,
        application_id: ApplicationId,
        version: int,
        starting_status: str,
    ) -> None:
        if self._fail_on_start:
            raise RuntimeError("simulated workflow start failure")
        self.started.append(
            StartedWorkflow(
                workflow_id=workflow_id,
                tenant_id=tenant_id,
                application_id=application_id,
                version=version,
                starting_status=starting_status,
            )
        )

    async def signal_review_decision(
        self, *, workflow_id: str, decision: str, reason: str, reviewer_id: str
    ) -> None:
        if self._fail_on_signal:
            raise RuntimeError("simulated signal failure")
        self.signaled.append(
            SentSignal(
                workflow_id=workflow_id, decision=decision, reason=reason, reviewer_id=reviewer_id
            )
        )


class FakeFileSafetyScanner(FileSafetyScanner):
    def __init__(
        self, *, detected_content_type: str = "application/pdf", page_count: int = 1
    ) -> None:
        self._report = FileSafetyReport(
            detected_content_type=detected_content_type, page_count=page_count
        )

    async def scan(
        self, *, data: bytes, filename: str, declared_content_type: str
    ) -> FileSafetyReport:
        return self._report


class FakeKycVerifier(KycVerifier):
    def __init__(self, result: KycVerificationResult) -> None:
        self._result = result

    async def check_connectivity(self) -> None:
        return None

    async def verify_identity(
        self,
        *,
        given_name: str,
        family_name: str,
        date_of_birth: date,
        synthetic_id: str,
        street_address: str,
        city: str,
    ) -> KycVerificationResult:
        return self._result


class FakeEmployerVerifier(EmployerVerifier):
    def __init__(self, result: EmploymentVerificationResult) -> None:
        self._result = result

    async def check_connectivity(self) -> None:
        return None

    async def verify_employment(
        self,
        *,
        given_name: str,
        family_name: str,
        synthetic_id: str,
        employer_name: str,
        declared_annual_income: int,
    ) -> EmploymentVerificationResult:
        return self._result


class FakeBureauClient(BureauClient):
    def __init__(self, result: CreditReport) -> None:
        self._result = result

    async def check_connectivity(self) -> None:
        return None

    async def get_credit_report(
        self, *, given_name: str, family_name: str, date_of_birth: date, synthetic_id: str
    ) -> CreditReport:
        return self._result


class FakeCoreBankingClient(CoreBankingClient):
    def __init__(self, result: TransactionHistory) -> None:
        self._result = result

    async def check_connectivity(self) -> None:
        return None

    async def get_transaction_history(
        self, *, given_name: str, family_name: str, synthetic_id: str, declared_annual_income: int
    ) -> TransactionHistory:
        return self._result
