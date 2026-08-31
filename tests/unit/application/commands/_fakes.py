"""In-memory fakes for the application-layer ports, used to unit-test command handlers without a
real database. Each fake enforces the same semantics the real Postgres-backed adapter promises
(tenant scoping, idempotency-key reservation, optimistic concurrency) so a test written against
the fake stays meaningful.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import TracebackType

from finassist.application.ports.applicant_repository import ApplicantRepository
from finassist.application.ports.application_repository import ApplicationRepository
from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.product_catalog import ProductCatalog
from finassist.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from finassist.domain.applications.applicant import Applicant
from finassist.domain.applications.application import Application
from finassist.domain.applications.events import DomainEvent
from finassist.domain.applications.exceptions import ConcurrencyConflictError
from finassist.domain.applications.product import Product
from finassist.domain.shared.identifiers import ApplicantId, ApplicationId, ProductId, TenantId


@dataclass
class FakeBackingStore:
    """Shared state across fake unit-of-work instances, simulating a database across
    transactions within one test."""

    applications: dict[tuple[str, str], Application] = field(default_factory=dict)
    applicants: dict[tuple[str, str], Applicant] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)
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


class FakeUnitOfWork(UnitOfWork):
    def __init__(self, store: FakeBackingStore, tenant_id: TenantId) -> None:
        self._store = store
        self._tenant_id = tenant_id
        self.applications = FakeApplicationRepository(store)
        self.applicants = FakeApplicantRepository(store)
        self.products = FakeProductCatalog(store)
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
