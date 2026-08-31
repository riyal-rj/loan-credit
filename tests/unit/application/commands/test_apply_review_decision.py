from __future__ import annotations

import pytest

from finassist.application.commands.apply_review_decision import (
    ApplyReviewDecisionCommand,
    ApplyReviewDecisionHandler,
)
from finassist.application.ports.review_queue_repository import ReviewQueueEntry
from finassist.domain.applications.exceptions import InvalidApplicationDataError
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import ApplicationId, TenantId, new_id

from ._fakes import FakeUnitOfWorkFactory
from ._helpers import NOW, make_product, seed_application_at


async def _seed_in_review(factory: FakeUnitOfWorkFactory, tenant_id: TenantId) -> str:
    product = make_product()
    factory.store.products[str(product.product_id)] = product
    application_id = await seed_application_at(
        factory,
        tenant_id=tenant_id,
        product=product,
        status=ApplicationStatus.AWAITING_HUMAN_REVIEW,
    )
    factory.store.review_queue_entries[(str(tenant_id), str(application_id))] = ReviewQueueEntry(
        application_id=application_id, tenant_id=tenant_id, entered_queue_at=NOW, status="pending"
    )
    return str(application_id)


@pytest.mark.asyncio
async def test_approved_decision_transitions_and_detaches_workflow() -> None:
    tenant_id = TenantId(new_id())
    factory = FakeUnitOfWorkFactory()
    application_id = await _seed_in_review(factory, tenant_id)
    handler = ApplyReviewDecisionHandler(uow_factory=factory, clock=FixedClock(NOW))

    result = await handler.handle(
        ApplyReviewDecisionCommand(
            tenant_id=tenant_id,
            application_id=ApplicationId(application_id),
            idempotency_key="k1",
            decision=ApplicationStatus.APPROVED,
            reason="looks good",
            reviewer_id="reviewer-1",
        )
    )

    assert result.status is ApplicationStatus.APPROVED
    saved = factory.store.applications[(str(tenant_id), application_id)]
    assert saved.active_workflow_id is None
    entry = factory.store.review_queue_entries[(str(tenant_id), application_id)]
    assert entry.status == "decided"
    assert entry.decision == "APPROVED"
    assert entry.reviewer_id == "reviewer-1"


@pytest.mark.asyncio
async def test_sla_timeout_escalation_has_no_reviewer_id() -> None:
    tenant_id = TenantId(new_id())
    factory = FakeUnitOfWorkFactory()
    application_id = await _seed_in_review(factory, tenant_id)
    handler = ApplyReviewDecisionHandler(uow_factory=factory, clock=FixedClock(NOW))

    result = await handler.handle(
        ApplyReviewDecisionCommand(
            tenant_id=tenant_id,
            application_id=ApplicationId(application_id),
            idempotency_key="k1",
            decision=ApplicationStatus.ESCALATED,
            reason="human review SLA timeout",
            reviewer_id=None,
        )
    )

    assert result.status is ApplicationStatus.ESCALATED
    entry = factory.store.review_queue_entries[(str(tenant_id), application_id)]
    assert entry.reviewer_id is None


@pytest.mark.asyncio
async def test_invalid_decision_value_is_rejected() -> None:
    tenant_id = TenantId(new_id())
    factory = FakeUnitOfWorkFactory()
    application_id = await _seed_in_review(factory, tenant_id)
    handler = ApplyReviewDecisionHandler(uow_factory=factory, clock=FixedClock(NOW))

    with pytest.raises(InvalidApplicationDataError):
        await handler.handle(
            ApplyReviewDecisionCommand(
                tenant_id=tenant_id,
                application_id=ApplicationId(application_id),
                idempotency_key="k1",
                decision=ApplicationStatus.DRAFT,
                reason="not a real review outcome",
                reviewer_id="reviewer-1",
            )
        )
