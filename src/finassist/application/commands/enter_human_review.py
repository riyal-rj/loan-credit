"""`EnterHumanReviewCommand`: invoked by `enter_human_review_activity`, once verification has run
(or been skipped for lack of documents -- see `advance_document_processing.py`).

A thin, idempotency-key-guarded wrapper around the shared `_enter_human_review.enter_human_review`
mutation, taking an explicit `reason` so the caller (the workflow, via the verification summary)
controls what a reviewer sees, instead of a hard-coded string.
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.commands._enter_human_review import enter_human_review
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    DuplicateRequestError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId

_OPERATION_NAME = "enter_human_review"


@dataclass(frozen=True, slots=True)
class EnterHumanReviewCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    idempotency_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class EnterHumanReviewResult:
    application_id: ApplicationId
    status: ApplicationStatus
    version: int


class EnterHumanReviewHandler:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def handle(self, command: EnterHumanReviewCommand) -> EnterHumanReviewResult:
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

            await enter_human_review(
                uow=uow, application=application, reason=command.reason, clock=self._clock
            )
            await uow.record_domain_events(application.pull_events())
            await uow.commit()

            return EnterHumanReviewResult(
                application_id=application.application_id,
                status=application.status,
                version=application.version,
            )
