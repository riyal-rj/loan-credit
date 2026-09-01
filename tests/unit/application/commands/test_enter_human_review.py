from __future__ import annotations

import pytest

from finassist.application.commands.enter_human_review import (
    EnterHumanReviewCommand,
    EnterHumanReviewHandler,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import TenantId, new_id

from ._fakes import FakeUnitOfWorkFactory
from ._helpers import NOW, make_product, seed_application_at


@pytest.mark.asyncio
async def test_escalates_with_the_given_reason_and_creates_queue_entry() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.VERIFICATION
    )
    handler = EnterHumanReviewHandler(uow_factory=factory, clock=FixedClock(NOW))

    result = await handler.handle(
        EnterHumanReviewCommand(
            tenant_id=tenant_id,
            application_id=application_id,
            idempotency_key="k1",
            reason="verification complete: 2 matched",
        )
    )

    assert result.status is ApplicationStatus.AWAITING_HUMAN_REVIEW
    entry = factory.store.review_queue_entries[(str(tenant_id), str(application_id))]
    assert entry.status == "pending"
