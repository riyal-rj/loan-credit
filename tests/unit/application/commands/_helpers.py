"""Shared test helpers for the Phase 3 command handler tests -- seeding a `Product` and an
`Application` already at a given status, via direct domain calls (not through a handler), so each
test file doesn't re-implement the same setup."""

from __future__ import annotations

from datetime import UTC, datetime

from finassist.domain.applications.application import Application
from finassist.domain.applications.product import Product
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import ApplicantId, ApplicationId, ProductId, TenantId
from finassist.domain.shared.money import Money

from ._fakes import FakeUnitOfWorkFactory

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_product(
    *, min_amount: str = "1000.00", max_amount: str = "25000.00", is_active: bool = True
) -> Product:
    return Product(
        product_id=ProductId(_uuid()),
        code="PERSONAL_LOAN_USD",
        name="Personal Loan",
        currency="USD",
        min_amount=Money.of(min_amount, "USD"),
        max_amount=Money.of(max_amount, "USD"),
        min_term_months=6,
        max_term_months=60,
        is_active=is_active,
    )


def _uuid() -> str:
    from finassist.domain.shared.identifiers import new_id

    return new_id()


async def seed_application_at(
    factory: FakeUnitOfWorkFactory,
    *,
    tenant_id: TenantId,
    product: Product,
    status: ApplicationStatus,
    requested_amount: str = "5000.00",
) -> ApplicationId:
    """Creates an `Application` and drives it (via direct `transition_to` calls, not through a
    command handler) to ``status``, then persists it. Only follows a real path through the state
    machine, so an unreachable target status raises the same `IllegalStateTransitionError` a real
    bug would."""
    application = Application.create(
        application_id=ApplicationId(_uuid()),
        tenant_id=tenant_id,
        applicant_id=ApplicantId(_uuid()),
        product=product,
        requested_amount=Money.of(requested_amount, "USD"),
        requested_term_months=24,
        clock=FixedClock(NOW),
    )
    application.pull_events()

    path: dict[ApplicationStatus, list[ApplicationStatus]] = {
        ApplicationStatus.DRAFT: [],
        ApplicationStatus.SUBMITTED: [ApplicationStatus.SUBMITTED],
        ApplicationStatus.INTAKE_VALIDATION: [
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.INTAKE_VALIDATION,
        ],
        ApplicationStatus.DOCUMENT_PROCESSING: [
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.INTAKE_VALIDATION,
            ApplicationStatus.DOCUMENT_PROCESSING,
        ],
        ApplicationStatus.VERIFICATION: [
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.INTAKE_VALIDATION,
            ApplicationStatus.DOCUMENT_PROCESSING,
            ApplicationStatus.VERIFICATION,
        ],
        ApplicationStatus.AWAITING_HUMAN_REVIEW: [
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.INTAKE_VALIDATION,
            ApplicationStatus.DOCUMENT_PROCESSING,
            ApplicationStatus.VERIFICATION,
            ApplicationStatus.AWAITING_HUMAN_REVIEW,
        ],
        ApplicationStatus.NEEDS_MORE_INFORMATION: [
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.INTAKE_VALIDATION,
            ApplicationStatus.DOCUMENT_PROCESSING,
            ApplicationStatus.VERIFICATION,
            ApplicationStatus.AWAITING_HUMAN_REVIEW,
            ApplicationStatus.NEEDS_MORE_INFORMATION,
        ],
    }
    for step in path[status]:
        application.transition_to(step, reason="test setup", clock=FixedClock(NOW))
    application.pull_events()

    async with factory.begin(tenant_id=tenant_id) as uow:
        await uow.applications.add(application)
        await uow.commit()
    return application.application_id
