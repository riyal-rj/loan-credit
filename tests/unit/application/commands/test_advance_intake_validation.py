from __future__ import annotations

import pytest

from finassist.application.commands.advance_intake_validation import (
    AdvanceIntakeValidationCommand,
    AdvanceIntakeValidationHandler,
)
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    DuplicateRequestError,
    ProductNotFoundError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import ApplicationId, TenantId, new_id

from ._fakes import FakeUnitOfWorkFactory
from ._helpers import NOW, make_product, seed_application_at


@pytest.mark.asyncio
async def test_accepted_request_advances_to_document_processing() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory,
        tenant_id=tenant_id,
        product=product,
        status=ApplicationStatus.SUBMITTED,
        requested_amount="5000.00",
    )
    handler = AdvanceIntakeValidationHandler(uow_factory=factory, clock=FixedClock(NOW))

    result = await handler.handle(
        AdvanceIntakeValidationCommand(
            tenant_id=tenant_id, application_id=application_id, idempotency_key="k1"
        )
    )

    assert result.accepted is True
    assert result.status is ApplicationStatus.DOCUMENT_PROCESSING


@pytest.mark.asyncio
async def test_out_of_bounds_request_escalates_to_human_review() -> None:
    # The real state machine only allows DECLINED to be reached from AWAITING_HUMAN_REVIEW/
    # ESCALATED (never automatically) -- an out-of-bounds request escalates with an explanatory
    # reason instead, exactly like a missing-document case does.
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
    handler = AdvanceIntakeValidationHandler(uow_factory=factory, clock=FixedClock(NOW))

    result = await handler.handle(
        AdvanceIntakeValidationCommand(
            tenant_id=tenant_id, application_id=application_id, idempotency_key="k1"
        )
    )

    assert result.accepted is False
    assert result.status is ApplicationStatus.AWAITING_HUMAN_REVIEW
    entry = factory.store.review_queue_entries[(str(tenant_id), str(application_id))]
    assert entry.status == "pending"


@pytest.mark.asyncio
async def test_unknown_application_raises() -> None:
    factory = FakeUnitOfWorkFactory(products=[make_product()])
    handler = AdvanceIntakeValidationHandler(uow_factory=factory, clock=FixedClock(NOW))

    with pytest.raises(ApplicationNotFoundError):
        await handler.handle(
            AdvanceIntakeValidationCommand(
                tenant_id=TenantId(new_id()),
                application_id=ApplicationId(new_id()),
                idempotency_key="k1",
            )
        )


@pytest.mark.asyncio
async def test_missing_product_raises() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory()  # product deliberately not registered
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.SUBMITTED
    )
    handler = AdvanceIntakeValidationHandler(uow_factory=factory, clock=FixedClock(NOW))

    with pytest.raises(ProductNotFoundError):
        await handler.handle(
            AdvanceIntakeValidationCommand(
                tenant_id=tenant_id, application_id=application_id, idempotency_key="k1"
            )
        )


@pytest.mark.asyncio
async def test_retry_with_same_idempotency_key_raises_duplicate() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.SUBMITTED
    )
    handler = AdvanceIntakeValidationHandler(uow_factory=factory, clock=FixedClock(NOW))
    command = AdvanceIntakeValidationCommand(
        tenant_id=tenant_id, application_id=application_id, idempotency_key="same-key"
    )

    await handler.handle(command)

    with pytest.raises(DuplicateRequestError):
        await handler.handle(command)
