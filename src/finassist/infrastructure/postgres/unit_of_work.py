"""`SqlAlchemyUnitOfWork`: one Postgres transaction, scoped to one tenant.

Implements docs/adr/0009: sets the RLS session variable before any other statement runs, writes
one outbox row and one hash-chained audit row per domain event in the same transaction, and
implements idempotency-key reservation via insert-and-catch-conflict (avoids a check-then-insert
race).
"""

from __future__ import annotations

from types import TracebackType

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from finassist.domain.applications.events import DomainEvent
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import TenantId
from finassist.infrastructure.postgres.audit_hash import GENESIS_HASH, compute_audit_hash
from finassist.infrastructure.postgres.event_mapping import event_to_record
from finassist.infrastructure.postgres.orm_models import (
    AuditEventRow,
    AuditHashRow,
    IdempotencyKeyRow,
    OutboxEventRow,
)
from finassist.infrastructure.postgres.product_catalog import SqlAlchemyProductCatalog
from finassist.infrastructure.postgres.repository import (
    SqlAlchemyApplicantRepository,
    SqlAlchemyApplicationRepository,
)

_SCHEMA_VERSION = 1


class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: TenantId,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._clock = clock
        self._id_generator = id_generator
        self._session: AsyncSession | None = None
        self._committed = False

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError(
                "SqlAlchemyUnitOfWork method called outside 'async with' (no active session)"
            )
        return self._session

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        await self._session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(self._tenant_id)},
        )
        self.applications = SqlAlchemyApplicationRepository(
            self._session, self._id_generator.new_id
        )
        self.applicants = SqlAlchemyApplicantRepository(self._session, self._clock)
        self.products = SqlAlchemyProductCatalog(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if not self._committed:
                await session.rollback()
        finally:
            await session.close()
            self._committed = False
            self._session = None

    async def commit(self) -> None:
        session = self._require_session()
        await session.commit()
        self._committed = True

    async def rollback(self) -> None:
        await self._require_session().rollback()

    async def record_domain_events(self, events: list[DomainEvent]) -> None:
        session = self._require_session()
        for event in events:
            event_type, aggregate_type, payload = event_to_record(event)
            event_id = self._id_generator.new_id()
            tenant_id = str(event.tenant_id)
            now = self._clock.now()

            session.add(
                OutboxEventRow(
                    event_id=event_id,
                    tenant_id=tenant_id,
                    event_type=event_type,
                    schema_version=_SCHEMA_VERSION,
                    occurred_at=event.occurred_at,
                    aggregate_type=aggregate_type,
                    aggregate_id=str(event.application_id),
                    correlation_id=None,
                    causation_id=None,
                    payload=payload,
                    published_at=None,
                    created_at=now,
                )
            )

            checkpoint = await session.get(AuditHashRow, tenant_id)
            prev_hash = checkpoint.latest_hash if checkpoint is not None else GENESIS_HASH
            new_hash = compute_audit_hash(
                prev_hash=prev_hash,
                event_id=event_id,
                event_type=event_type,
                aggregate_id=str(event.application_id),
                occurred_at=event.occurred_at,
                payload=payload,
            )
            session.add(
                AuditEventRow(
                    event_id=event_id,
                    tenant_id=tenant_id,
                    occurred_at=event.occurred_at,
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=str(event.application_id),
                    payload=payload,
                    correlation_id=None,
                    prev_hash=prev_hash,
                    hash=new_hash,
                    created_at=now,
                )
            )
            if checkpoint is None:
                session.add(
                    AuditHashRow(
                        tenant_id=tenant_id,
                        latest_event_id=event_id,
                        latest_hash=new_hash,
                        updated_at=now,
                    )
                )
            else:
                checkpoint.latest_event_id = event_id
                checkpoint.latest_hash = new_hash
                checkpoint.updated_at = now

        await session.flush()

    async def reserve_idempotency_key(self, *, key: str, operation_name: str) -> bool:
        session = self._require_session()
        session.add(
            IdempotencyKeyRow(
                tenant_id=str(self._tenant_id),
                operation_name=operation_name,
                idempotency_key=key,
                reserved_at=self._clock.now(),
            )
        )
        try:
            await session.flush()
        except IntegrityError:
            # Duplicate reservation. The caller raises DuplicateRequestError immediately and the
            # `async with` block exits without further use of this session, so `__aexit__`'s
            # rollback is sufficient cleanup -- no need to roll back proactively here.
            return False
        return True


class SqlAlchemyUnitOfWorkFactory(UnitOfWorkFactory):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_generator = id_generator

    def begin(self, *, tenant_id: TenantId) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            self._session_factory,
            tenant_id=tenant_id,
            clock=self._clock,
            id_generator=self._id_generator,
        )
