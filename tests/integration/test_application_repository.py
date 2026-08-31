"""Integration tests against a real PostgreSQL container (master instruction §21.1).

Covers what a pure in-memory fake cannot prove: the RLS tenant-isolation policy actually rejects
cross-tenant reads at the database layer, the outbox row and hash-chained audit row are written
in the same transaction as the aggregate, and optimistic concurrency is enforced by the real
`UPDATE`/version check rather than the fake's Python-level comparison.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.application.commands.create_application import (
    CreateApplicationCommand,
    CreateApplicationHandler,
)
from finassist.application.commands.submit_application import (
    SubmitApplicationCommand,
    SubmitApplicationHandler,
)
from finassist.application.ports.id_generator import UuidIdGenerator
from finassist.domain.applications.exceptions import (
    ConcurrencyConflictError,
    ProductNotFoundError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import ProductId, TenantId, new_id
from finassist.domain.shared.money import Money
from finassist.infrastructure.postgres.orm_models import (
    AuditEventRow,
    AuditHashRow,
    OutboxEventRow,
)
from finassist.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWorkFactory

pytestmark = pytest.mark.asyncio(loop_scope="session")

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def _seed_tenant_and_product(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: str,
    product_id: str,
) -> None:
    # Onboarding a tenant is an administrative action -- `finassist_app` only has SELECT on
    # `identity.tenants` (docs/adr/0009), so this insert must go through the migration/admin role.
    async with admin_session_factory() as admin_session:
        await admin_session.execute(
            text(
                "INSERT INTO identity.tenants (tenant_id, name, created_at) "
                "VALUES (:id, :name, now())"
            ),
            {"id": tenant_id, "name": f"tenant-{tenant_id[:8]}"},
        )
        await admin_session.commit()

    async with session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
        )
        await session.execute(
            text(
                "INSERT INTO applications.products "
                "(product_id, tenant_id, code, name, currency, min_amount, max_amount, "
                "min_term_months, max_term_months, is_active, created_at) "
                "VALUES (:product_id, :tenant_id, :code, :name, 'USD', 1000.00, 25000.00, "
                "6, 60, true, now())"
            ),
            {
                "product_id": product_id,
                "tenant_id": tenant_id,
                "code": f"CODE-{product_id[:8]}",
                "name": "Test Personal Loan",
            },
        )
        await session.commit()


def _uow_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyUnitOfWorkFactory:
    return SqlAlchemyUnitOfWorkFactory(
        session_factory, clock=FixedClock(_NOW), id_generator=UuidIdGenerator()
    )


def _create_command(
    tenant_id: str, product_id: str, idempotency_key: str
) -> CreateApplicationCommand:
    return CreateApplicationCommand(
        tenant_id=TenantId(tenant_id),
        idempotency_key=idempotency_key,
        applicant_given_name="Ada",
        applicant_family_name="Lovelace",
        applicant_date_of_birth=date(1990, 1, 1),
        applicant_email="ada@example.test",
        product_id=ProductId(product_id),
        requested_amount=Money.of("5000.00", "USD"),
        requested_term_months=24,
    )


async def test_create_and_submit_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, product_id = new_id(), new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_id, product_id=product_id
    )
    uow_factory = _uow_factory(session_factory)

    create_handler = CreateApplicationHandler(
        uow_factory=uow_factory, id_generator=UuidIdGenerator(), clock=FixedClock(_NOW)
    )
    create_result = await create_handler.handle(_create_command(tenant_id, product_id, new_id()))
    assert create_result.status is ApplicationStatus.DRAFT

    async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
        loaded = await uow.applications.get(
            tenant_id=TenantId(tenant_id), application_id=create_result.application_id
        )
    assert loaded is not None
    assert loaded.requested_amount == Money.of("5000.00", "USD")

    submit_handler = SubmitApplicationHandler(uow_factory=uow_factory, clock=FixedClock(_NOW))
    submit_result = await submit_handler.handle(
        SubmitApplicationCommand(
            tenant_id=TenantId(tenant_id),
            application_id=create_result.application_id,
            idempotency_key=new_id(),
        )
    )
    assert submit_result.status is ApplicationStatus.SUBMITTED
    assert submit_result.version == 2


async def test_rls_blocks_reading_another_tenants_application(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_tenant, other_tenant = new_id(), new_id()
    product_id = new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=owner_tenant, product_id=product_id
    )
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=other_tenant, product_id=new_id()
    )
    uow_factory = _uow_factory(session_factory)

    create_handler = CreateApplicationHandler(
        uow_factory=uow_factory, id_generator=UuidIdGenerator(), clock=FixedClock(_NOW)
    )
    result = await create_handler.handle(_create_command(owner_tenant, product_id, new_id()))

    async with uow_factory.begin(tenant_id=TenantId(other_tenant)) as uow:
        cross_tenant_read = await uow.applications.get(
            tenant_id=TenantId(other_tenant), application_id=result.application_id
        )
    assert cross_tenant_read is None

    async with uow_factory.begin(tenant_id=TenantId(owner_tenant)) as uow:
        same_tenant_read = await uow.applications.get(
            tenant_id=TenantId(owner_tenant), application_id=result.application_id
        )
    assert same_tenant_read is not None


async def test_rls_blocks_reading_another_tenants_product(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_tenant, other_tenant = new_id(), new_id()
    product_id = new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=owner_tenant, product_id=product_id
    )
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=other_tenant, product_id=new_id()
    )
    uow_factory = _uow_factory(session_factory)

    create_handler = CreateApplicationHandler(
        uow_factory=uow_factory, id_generator=UuidIdGenerator(), clock=FixedClock(_NOW)
    )

    # `other_tenant` trying to create an application against `owner_tenant`'s product must fail
    # as "not found" -- RLS makes the product invisible, the handler cannot distinguish this from
    # the product never having existed.
    with pytest.raises(ProductNotFoundError):
        await create_handler.handle(_create_command(other_tenant, product_id, new_id()))


async def test_stale_save_raises_concurrency_conflict(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, product_id = new_id(), new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_id, product_id=product_id
    )
    uow_factory = _uow_factory(session_factory)

    create_handler = CreateApplicationHandler(
        uow_factory=uow_factory, id_generator=UuidIdGenerator(), clock=FixedClock(_NOW)
    )
    result = await create_handler.handle(_create_command(tenant_id, product_id, new_id()))

    async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
        stale = await uow.applications.get(
            tenant_id=TenantId(tenant_id), application_id=result.application_id
        )
        assert stale is not None
        stale.submit(clock=FixedClock(_NOW))
        await uow.applications.save(stale)
        await uow.record_domain_events(stale.pull_events())
        await uow.commit()

    async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
        with pytest.raises(ConcurrencyConflictError):
            await uow.applications.save(stale)


async def test_domain_events_write_outbox_and_hash_chained_audit_rows(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, product_id = new_id(), new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_id, product_id=product_id
    )
    uow_factory = _uow_factory(session_factory)

    create_handler = CreateApplicationHandler(
        uow_factory=uow_factory, id_generator=UuidIdGenerator(), clock=FixedClock(_NOW)
    )
    result = await create_handler.handle(_create_command(tenant_id, product_id, new_id()))

    async with session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
        )
        outbox_rows = (
            (
                await session.execute(
                    select(OutboxEventRow).where(
                        OutboxEventRow.aggregate_id == str(result.application_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        audit_rows = (
            (
                await session.execute(
                    select(AuditEventRow).where(
                        AuditEventRow.aggregate_id == str(result.application_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        checkpoint = await session.get(AuditHashRow, tenant_id)

    assert len(outbox_rows) == 1
    assert outbox_rows[0].event_type == "ApplicationCreated"
    assert outbox_rows[0].published_at is None

    assert len(audit_rows) == 1
    assert audit_rows[0].event_type == "ApplicationCreated"
    assert checkpoint is not None
    assert checkpoint.latest_hash == audit_rows[0].hash


async def test_duplicate_idempotency_key_rejected_at_database_level(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, product_id = new_id(), new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_id, product_id=product_id
    )
    uow_factory = _uow_factory(session_factory)
    key = new_id()

    async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
        first = await uow.reserve_idempotency_key(key=key, operation_name="test_op")
        await uow.commit()
    assert first is True

    async with uow_factory.begin(tenant_id=TenantId(tenant_id)) as uow:
        second = await uow.reserve_idempotency_key(key=key, operation_name="test_op")
    assert second is False
