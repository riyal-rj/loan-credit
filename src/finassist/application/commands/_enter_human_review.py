"""Shared "escalate to human review" mutation, used by every automated stage that has nowhere
else legal to go (docs/adr/0011).

Not its own command/activity: the real state machine (`domain.applications.status`, Phase 1B,
exhaustively property-tested) only allows `DECLINED`/`APPROVED`/`NEEDS_MORE_INFORMATION` to be
reached *from* `AWAITING_HUMAN_REVIEW` or `ESCALATED` -- there is no automated path to any of
those outcomes, which is exactly master instruction invariant §5.1 ("no final credit decision
without an authenticated, authorized human action") holding at the type/transition level, not just
by convention. Consequently every automated stage that would otherwise want to auto-reject or
auto-request-more-information (out-of-bounds intake, missing documents) instead escalates to a
human with an explanatory reason -- this function is that single mutation, called from within the
caller's own transaction (no separate idempotency key/uow of its own).
"""

from __future__ import annotations

from finassist.application.ports.review_queue_repository import ReviewQueueEntry
from finassist.application.ports.unit_of_work import UnitOfWork
from finassist.domain.applications.application import Application
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock


async def enter_human_review(
    *, uow: UnitOfWork, application: Application, reason: str, clock: Clock
) -> None:
    application.transition_to(ApplicationStatus.AWAITING_HUMAN_REVIEW, reason=reason, clock=clock)
    await uow.applications.save(application)
    await uow.review_queue.add(
        ReviewQueueEntry(
            application_id=application.application_id,
            tenant_id=application.tenant_id,
            entered_queue_at=clock.now(),
            status="pending",
        )
    )
