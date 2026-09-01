"""Transaction-boundary port.

One `UnitOfWork` instance == one database transaction, already scoped to a single tenant (the
factory sets the RLS session variable before any query can run -- docs/adr/0009 decision 1). This
is also where the outbox write and idempotency-key reservation happen, in the same transaction as
the aggregate save, satisfying invariant §5.7 (no dual-write, no duplicate side effects on retry).
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, runtime_checkable

from finassist.application.ports.applicant_repository import ApplicantRepository
from finassist.application.ports.application_repository import ApplicationRepository
from finassist.application.ports.document_repository import DocumentRepository
from finassist.application.ports.extraction_repository import ExtractionRepository
from finassist.application.ports.product_catalog import ProductCatalog
from finassist.application.ports.review_queue_repository import ReviewQueueRepository
from finassist.application.ports.verification_repository import VerificationRepository
from finassist.domain.applications.events import DomainEvent
from finassist.domain.shared.identifiers import TenantId


@runtime_checkable
class UnitOfWork(Protocol):
    applications: ApplicationRepository
    applicants: ApplicantRepository
    products: ProductCatalog
    documents: DocumentRepository
    review_queue: ReviewQueueRepository
    extraction: ExtractionRepository
    verification: VerificationRepository

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None:
        """Commit the transaction. Must be called explicitly -- `__aexit__` rolls back by
        default so an exception (including one raised after `save` but before `commit`) never
        leaves a half-applied change committed."""
        ...

    async def rollback(self) -> None: ...

    async def record_domain_events(self, events: list[DomainEvent]) -> None:
        """Append one outbox row per event, in this transaction."""
        ...

    async def reserve_idempotency_key(self, *, key: str, operation_name: str) -> bool:
        """Atomically reserve `key` for `operation_name` in this tenant's scope.

        Returns `True` if this call reserved it (caller should proceed), `False` if it was
        already reserved (caller should treat this as a duplicate request and return the prior
        outcome rather than repeating the side effect).
        """
        ...


@runtime_checkable
class UnitOfWorkFactory(Protocol):
    def begin(self, *, tenant_id: TenantId) -> UnitOfWork:
        """Return a new, not-yet-entered `UnitOfWork` scoped to `tenant_id`. Use as:
        ``async with factory.begin(tenant_id=tenant_id) as uow: ...``
        """
        ...
