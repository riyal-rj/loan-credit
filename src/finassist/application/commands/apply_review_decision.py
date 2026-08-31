"""`ApplyReviewDecisionCommand`: invoked by `apply_review_decision_activity`, in response to either
a `submit_review_decision` Temporal signal (a human's decision, via
`POST /internal/applications/{id}/review-decisions`) or the workflow's own SLA timer firing
(`reviewer_id=None`, `decision=ESCALATED`).

Applies the decision to the aggregate and detaches the workflow: whichever outcome is recorded,
*this* workflow execution ends after applying it (docs/adr/0011) -- there is no Phase 3 mechanism
to resume a case out of `ESCALATED` back into an active workflow; that is Phase 7 scope.
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    DuplicateRequestError,
    InvalidApplicationDataError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId

_OPERATION_NAME = "apply_review_decision"

_ALLOWED_DECISIONS = frozenset(
    {
        ApplicationStatus.APPROVED,
        ApplicationStatus.DECLINED,
        ApplicationStatus.NEEDS_MORE_INFORMATION,
        ApplicationStatus.ESCALATED,
    }
)


@dataclass(frozen=True, slots=True)
class ApplyReviewDecisionCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    idempotency_key: str
    decision: ApplicationStatus
    reason: str
    reviewer_id: str | None


@dataclass(frozen=True, slots=True)
class ApplyReviewDecisionResult:
    application_id: ApplicationId
    status: ApplicationStatus
    version: int


class ApplyReviewDecisionHandler:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def handle(self, command: ApplyReviewDecisionCommand) -> ApplyReviewDecisionResult:
        if command.decision not in _ALLOWED_DECISIONS:
            raise InvalidApplicationDataError(
                f"decision {command.decision.value!r} is not a valid human-review outcome"
            )

        async with self._uow_factory.begin(tenant_id=command.tenant_id) as uow:
            reserved = await uow.reserve_idempotency_key(
                key=command.idempotency_key, operation_name=_OPERATION_NAME
            )
            if not reserved:
                raise DuplicateRequestError(_OPERATION_NAME, command.idempotency_key)

            application = await uow.applications.get(
                tenant_id=command.tenant_id, application_id=command.application_id
            )
            if application is None:
                raise ApplicationNotFoundError(str(command.application_id))

            application.transition_to(command.decision, reason=command.reason, clock=self._clock)
            application.detach_workflow()

            now = self._clock.now()
            await uow.review_queue.mark_decided(
                tenant_id=command.tenant_id,
                application_id=command.application_id,
                decision=command.decision.value,
                reason=command.reason,
                reviewer_id=command.reviewer_id,
                decided_at=now,
            )
            await uow.applications.save(application)
            await uow.record_domain_events(application.pull_events())
            await uow.commit()

            return ApplyReviewDecisionResult(
                application_id=application.application_id,
                status=application.status,
                version=application.version,
            )
