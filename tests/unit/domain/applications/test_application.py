from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finassist.domain.applications.application import Application
from finassist.domain.applications.events import ApplicationCreated, ApplicationStateChanged
from finassist.domain.applications.exceptions import IllegalStateTransitionError
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

_FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


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


def _create_application(clock: FixedClock | None = None) -> Application:
    return Application.create(
        application_id=ApplicationId(new_id()),
        tenant_id=TenantId(new_id()),
        applicant_id=ApplicantId(new_id()),
        product=_product(),
        requested_amount=Money.of("5000.00", "USD"),
        requested_term_months=24,
        clock=clock or FixedClock(_FIXED_NOW),
    )


def test_create_starts_in_draft_with_version_one() -> None:
    application = _create_application()
    assert application.status is ApplicationStatus.DRAFT
    assert application.version == 1
    assert application.created_at == _FIXED_NOW
    assert application.updated_at == _FIXED_NOW


def test_create_raises_application_created_event() -> None:
    application = _create_application()
    events = application.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], ApplicationCreated)
    assert events[0].application_id == application.application_id


def test_pull_events_drains_the_queue() -> None:
    application = _create_application()
    first_pull = application.pull_events()
    second_pull = application.pull_events()
    assert len(first_pull) == 1
    assert second_pull == []


def test_rejects_non_positive_requested_amount() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        Application.create(
            application_id=ApplicationId(new_id()),
            tenant_id=TenantId(new_id()),
            applicant_id=ApplicantId(new_id()),
            product=_product(),
            requested_amount=Money.of("0.00", "USD"),
            requested_term_months=24,
            clock=FixedClock(_FIXED_NOW),
        )


def test_rejects_non_positive_term() -> None:
    with pytest.raises(ValueError, match="requested_term_months must be at least 1"):
        Application.create(
            application_id=ApplicationId(new_id()),
            tenant_id=TenantId(new_id()),
            applicant_id=ApplicantId(new_id()),
            product=_product(),
            requested_amount=Money.of("5000.00", "USD"),
            requested_term_months=0,
            clock=FixedClock(_FIXED_NOW),
        )


def test_submit_transitions_and_bumps_version() -> None:
    application = _create_application()
    application.pull_events()
    later = datetime(2026, 1, 2, tzinfo=UTC)

    application.submit(clock=FixedClock(later))

    assert application.status is ApplicationStatus.SUBMITTED
    assert application.version == 2
    assert application.updated_at == later
    assert application.created_at == _FIXED_NOW  # created_at never changes


def test_submit_raises_state_changed_event() -> None:
    application = _create_application()
    application.pull_events()

    application.submit(clock=FixedClock(_FIXED_NOW))

    events = application.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], ApplicationStateChanged)
    assert events[0].previous_status is ApplicationStatus.DRAFT
    assert events[0].new_status is ApplicationStatus.SUBMITTED


def test_illegal_transition_raises_and_does_not_mutate_state() -> None:
    application = _create_application()
    application.pull_events()

    with pytest.raises(IllegalStateTransitionError):
        application.transition_to(
            ApplicationStatus.APPROVED, reason="skip ahead", clock=FixedClock(_FIXED_NOW)
        )

    assert application.status is ApplicationStatus.DRAFT
    assert application.version == 1
    assert application.pull_events() == []


def test_cancel_from_draft() -> None:
    application = _create_application()
    application.cancel(reason="applicant withdrew", clock=FixedClock(_FIXED_NOW))
    assert application.status is ApplicationStatus.CANCELLED


def test_cannot_transition_out_of_terminal_state() -> None:
    application = _create_application()
    application.cancel(reason="applicant withdrew", clock=FixedClock(_FIXED_NOW))

    with pytest.raises(IllegalStateTransitionError):
        application.submit(clock=FixedClock(_FIXED_NOW))
