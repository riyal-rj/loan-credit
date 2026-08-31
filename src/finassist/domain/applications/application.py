"""The `Application` aggregate root -- the applications bounded context's transactional boundary.

Every consequential change to a case's state goes through this class so invariants §5.6
(deterministic, concurrency-safe, auditable transitions) and §5.7 (no duplicate side effects on
retry) are enforced in one place. Repositories persist this aggregate and drain its pending
domain events into the outbox in the same transaction (docs/adr/0009 decision 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from finassist.domain.applications.events import (
    ApplicationCreated,
    ApplicationStateChanged,
    DomainEvent,
)
from finassist.domain.applications.exceptions import IllegalStateTransitionError
from finassist.domain.applications.product import Product
from finassist.domain.applications.status import ApplicationStatus, is_legal_transition
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicantId, ApplicationId, ProductId, TenantId
from finassist.domain.shared.money import Money


@dataclass(slots=True)
class Application:
    application_id: ApplicationId
    tenant_id: TenantId
    applicant_id: ApplicantId
    product_id: ProductId
    requested_amount: Money
    requested_term_months: int
    status: ApplicationStatus
    version: int
    created_at: datetime
    updated_at: datetime
    active_workflow_id: str | None = None
    """The Temporal workflow ID currently orchestrating this application version, or `None` if
    none is running (Phase 3). Deliberately plain bookkeeping, not state-machine-governed: it is
    set once by whichever command starts a workflow (`submit`/resubmit) and cleared once the
    workflow's terminal activity applies a decision -- see `finassist.infrastructure.temporal`.
    Kept on the aggregate (rather than re-derived from `version`) because `version` keeps
    incrementing as the *same* workflow execution drives the case through automated activities, so
    it cannot be used to reconstruct the workflow ID a signal must be sent to."""
    _pending_events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        *,
        application_id: ApplicationId,
        tenant_id: TenantId,
        applicant_id: ApplicantId,
        product: Product,
        requested_amount: Money,
        requested_term_months: int,
        clock: Clock,
    ) -> Application:
        if requested_amount.is_negative() or requested_amount.is_zero():
            raise ValueError("requested_amount must be positive")
        if requested_term_months < 1:
            raise ValueError("requested_term_months must be at least 1")

        now = clock.now()
        application = cls(
            application_id=application_id,
            tenant_id=tenant_id,
            applicant_id=applicant_id,
            product_id=product.product_id,
            requested_amount=requested_amount,
            requested_term_months=requested_term_months,
            status=ApplicationStatus.DRAFT,
            version=1,
            created_at=now,
            updated_at=now,
        )
        application._pending_events.append(
            ApplicationCreated(
                application_id=application_id,
                tenant_id=tenant_id,
                occurred_at=now,
                product_id=str(product.product_id),
            )
        )
        return application

    def transition_to(self, new_status: ApplicationStatus, *, reason: str, clock: Clock) -> None:
        """The only method permitted to change `status`. Raises `IllegalStateTransitionError`
        for any transition not present in `status.ALLOWED_TRANSITIONS`, including any attempt to
        leave a terminal status."""
        if not is_legal_transition(self.status, new_status):
            raise IllegalStateTransitionError(self.status, new_status)

        now = clock.now()
        previous_status = self.status
        self.status = new_status
        self.version += 1
        self.updated_at = now
        self._pending_events.append(
            ApplicationStateChanged(
                application_id=self.application_id,
                tenant_id=self.tenant_id,
                occurred_at=now,
                previous_status=previous_status,
                new_status=new_status,
                reason=reason,
                version=self.version,
            )
        )

    def submit(self, *, clock: Clock) -> None:
        self.transition_to(ApplicationStatus.SUBMITTED, reason="applicant submitted", clock=clock)

    def cancel(self, *, reason: str, clock: Clock) -> None:
        self.transition_to(ApplicationStatus.CANCELLED, reason=reason, clock=clock)

    def attach_workflow(self, workflow_id: str) -> None:
        """Record that ``workflow_id`` is now the active Temporal workflow for this version.

        Called by `submit`/resubmit command handlers immediately before commit, so the ID is
        durable before the (best-effort, outside-the-transaction) call that actually starts it."""
        self.active_workflow_id = workflow_id

    def detach_workflow(self) -> None:
        """Clear the active workflow ID once its execution has ended (a decision was applied)."""
        self.active_workflow_id = None

    def pull_events(self) -> list[DomainEvent]:
        """Drain and return pending domain events. Call exactly once per unit of work, after the
        aggregate has been persisted, so events reach the outbox in the same transaction that
        made them true."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events
