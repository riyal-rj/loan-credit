"""`AdvanceDocumentProcessingCommand`: invoked by `check_required_documents_activity`.

At least one uploaded document: `DOCUMENT_PROCESSING -> VERIFICATION` only -- stops there (Phase 4:
`extract_document_facts_activity`/`verify_facts_activity` run next, then
`enter_human_review_activity` escalates with a reason citing the real verification outcome; see
`finassist.infrastructure.temporal.workflows`). Zero documents: escalates directly with a reason
explaining why -- there is no automated `NEEDS_MORE_INFORMATION` path (see
`_enter_human_review.py`'s docstring); a human reviewer decides that outcome from
`AWAITING_HUMAN_REVIEW`, and there is nothing to extract/verify without a document anyway.
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

_OPERATION_NAME = "advance_document_processing"


@dataclass(frozen=True, slots=True)
class AdvanceDocumentProcessingCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class AdvanceDocumentProcessingResult:
    application_id: ApplicationId
    status: ApplicationStatus
    version: int
    document_count: int


class AdvanceDocumentProcessingHandler:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def handle(
        self, command: AdvanceDocumentProcessingCommand
    ) -> AdvanceDocumentProcessingResult:
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

            document_count = await uow.documents.count_for_application(
                tenant_id=command.tenant_id, application_id=command.application_id
            )
            if document_count >= 1:
                application.transition_to(
                    ApplicationStatus.VERIFICATION,
                    reason=f"{document_count} document(s) present",
                    clock=self._clock,
                )
                await uow.applications.save(application)
            else:
                await enter_human_review(
                    uow=uow,
                    application=application,
                    reason="no documents uploaded -- requires human review",
                    clock=self._clock,
                )

            await uow.record_domain_events(application.pull_events())
            await uow.commit()

            return AdvanceDocumentProcessingResult(
                application_id=application.application_id,
                status=application.status,
                version=application.version,
                document_count=document_count,
            )
