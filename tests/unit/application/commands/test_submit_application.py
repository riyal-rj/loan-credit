from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finassist.application.commands.submit_application import (
    SubmitApplicationCommand,
    SubmitApplicationHandler,
)
from finassist.domain.applications.application import Application
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    ConcurrencyConflictError,
    DuplicateRequestError,
)
from finassist.domain.applications.product import Product
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import (
    ApplicantId,
    ApplicationId,
    ProductId,
    TenantId,
    new_id,
)
from finassist.domain.shared.money import Money

from ._fakes import FakeUnitOfWorkFactory

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _product() -> Product:
    return Product(
        product_id=ProductId(new_id()),
        code="PERSONAL_LOAN_USD",
        name="Personal Loan",
        currency="USD",
        min_amount=Money.of("1000.00", "USD"),
        max_amount=Money.of("25000.00", "USD"),
        min_term_months=6,
        max_term_months=60,
        is_active=True,
    )


async def _seed_draft_application(
    factory: FakeUnitOfWorkFactory, tenant_id: TenantId
) -> ApplicationId:
    application = Application.create(
        application_id=ApplicationId(new_id()),
        tenant_id=tenant_id,
        applicant_id=ApplicantId(new_id()),
        product=_product(),
        requested_amount=Money.of("5000.00", "USD"),
        requested_term_months=24,
        clock=FixedClock(_NOW),
    )
    application.pull_events()
    async with factory.begin(tenant_id=tenant_id) as uow:
        await uow.applications.add(application)
        await uow.commit()
    return application.application_id


@pytest.mark.asyncio
async def test_submit_transitions_draft_to_submitted() -> None:
    factory = FakeUnitOfWorkFactory()
    tenant_id = TenantId(new_id())
    application_id = await _seed_draft_application(factory, tenant_id)
    handler = SubmitApplicationHandler(uow_factory=factory, clock=FixedClock(_NOW))

    result = await handler.handle(
        SubmitApplicationCommand(
            tenant_id=tenant_id, application_id=application_id, idempotency_key="key-1"
        )
    )

    assert result.status is ApplicationStatus.SUBMITTED
    assert result.version == 2


@pytest.mark.asyncio
async def test_submit_unknown_application_raises() -> None:
    factory = FakeUnitOfWorkFactory()
    handler = SubmitApplicationHandler(uow_factory=factory, clock=FixedClock(_NOW))

    with pytest.raises(ApplicationNotFoundError):
        await handler.handle(
            SubmitApplicationCommand(
                tenant_id=TenantId(new_id()),
                application_id=ApplicationId(new_id()),
                idempotency_key="key-1",
            )
        )


@pytest.mark.asyncio
async def test_submit_is_idempotent_on_retry() -> None:
    factory = FakeUnitOfWorkFactory()
    tenant_id = TenantId(new_id())
    application_id = await _seed_draft_application(factory, tenant_id)
    handler = SubmitApplicationHandler(uow_factory=factory, clock=FixedClock(_NOW))
    command = SubmitApplicationCommand(
        tenant_id=tenant_id, application_id=application_id, idempotency_key="retry-key"
    )

    await handler.handle(command)

    with pytest.raises(DuplicateRequestError):
        await handler.handle(command)


@pytest.mark.asyncio
async def test_stale_write_raises_concurrency_conflict() -> None:
    factory = FakeUnitOfWorkFactory()
    tenant_id = TenantId(new_id())
    application_id = await _seed_draft_application(factory, tenant_id)

    async with factory.begin(tenant_id=tenant_id) as uow:
        stale_copy = await uow.applications.get(tenant_id=tenant_id, application_id=application_id)
        assert stale_copy is not None
        stale_copy.submit(clock=FixedClock(_NOW))

    # a concurrent writer saves first, advancing the stored version to 2
    handler = SubmitApplicationHandler(uow_factory=factory, clock=FixedClock(_NOW))
    await handler.handle(
        SubmitApplicationCommand(
            tenant_id=tenant_id, application_id=application_id, idempotency_key="winner"
        )
    )

    # the stale in-memory copy (still believing the prior version was 1) tries to save version 2
    async with factory.begin(tenant_id=tenant_id) as uow:
        with pytest.raises(ConcurrencyConflictError):
            await uow.applications.save(stale_copy)


@pytest.mark.asyncio
async def test_another_tenants_application_is_not_found() -> None:
    factory = FakeUnitOfWorkFactory()
    owner_tenant = TenantId(new_id())
    application_id = await _seed_draft_application(factory, owner_tenant)
    handler = SubmitApplicationHandler(uow_factory=factory, clock=FixedClock(_NOW))

    with pytest.raises(ApplicationNotFoundError):
        await handler.handle(
            SubmitApplicationCommand(
                tenant_id=TenantId(new_id()),
                application_id=application_id,
                idempotency_key="key-1",
            )
        )
