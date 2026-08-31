"""Property tests for the application state machine (master instruction §21.1: "Property-based
tests for ... policy boundaries").

Exhaustively checks every (source, target) pair in `ApplicationStatus` against
`Application.transition_to`, rather than hand-picking a few examples -- this is what actually
proves "cannot skip pipeline steps" and "terminal states are truly terminal" for *every* status,
not just the ones a hand-written test happened to think of.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from finassist.domain.applications.application import Application
from finassist.domain.applications.exceptions import IllegalStateTransitionError
from finassist.domain.applications.product import Product
from finassist.domain.applications.status import ApplicationStatus, is_legal_transition
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

_STATUS_STRATEGY = st.sampled_from(list(ApplicationStatus))


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


def _fresh_application(initial_status: ApplicationStatus) -> Application:
    application = Application.create(
        application_id=ApplicationId(new_id()),
        tenant_id=TenantId(new_id()),
        applicant_id=ApplicantId(new_id()),
        product=_product(),
        requested_amount=Money.of("5000.00", "USD"),
        requested_term_months=24,
        clock=FixedClock(_FIXED_NOW),
    )
    application.status = initial_status  # force into an arbitrary state for the property check
    application.pull_events()
    return application


@given(source=_STATUS_STRATEGY, target=_STATUS_STRATEGY)
def test_transition_outcome_matches_the_allowed_transitions_table(
    source: ApplicationStatus, target: ApplicationStatus
) -> None:
    application = _fresh_application(source)
    starting_version = application.version

    if is_legal_transition(source, target):
        application.transition_to(target, reason="property test", clock=FixedClock(_FIXED_NOW))
        assert application.status is target
        assert application.version == starting_version + 1
        assert len(application.pull_events()) == 1
    else:
        try:
            application.transition_to(target, reason="property test", clock=FixedClock(_FIXED_NOW))
        except IllegalStateTransitionError:
            pass
        else:
            raise AssertionError(f"expected {source} -> {target} to be illegal")
        # an illegal transition must never mutate state
        assert application.status is source
        assert application.version == starting_version
        assert application.pull_events() == []


@given(status=_STATUS_STRATEGY)
def test_every_status_can_reach_some_terminal_status_or_is_terminal(
    status: ApplicationStatus,
) -> None:
    """No status is a dead end that can never resolve to a final decision (directly or via one
    more hop) -- a real invariant a hand-written test could easily miss for a status added later."""
    from finassist.domain.applications.status import ALLOWED_TRANSITIONS, is_terminal

    if is_terminal(status):
        return

    reachable_in_two_hops = set(ALLOWED_TRANSITIONS[status])
    for one_hop in list(reachable_in_two_hops):
        reachable_in_two_hops.update(ALLOWED_TRANSITIONS[one_hop])

    terminal_statuses = {s for s in ApplicationStatus if is_terminal(s)}
    assert (
        reachable_in_two_hops & terminal_statuses
    ), f"{status} cannot reach any terminal status within two transitions"
