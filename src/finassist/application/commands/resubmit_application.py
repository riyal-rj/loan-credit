"""`ResubmitApplicationCommand`: `POST /applications/{application_id}/resubmit`.

Valid only from `NEEDS_MORE_INFORMATION` (enforced by `Application.transition_to`'s state-machine
check, not a separate guard here). Per docs/adr/0002, resubmission starts a *new* workflow
execution -- it never signals or reopens the closed execution from before `NEEDS_MORE_INFORMATION`.
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.commands._workflow_id import application_workflow_id
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.application.ports.workflow_runner import WorkflowRunner
from finassist.bootstrap.logging import get_logger
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    DuplicateRequestError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId

_OPERATION_NAME = "resubmit_application"

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResubmitApplicationCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ResubmitApplicationResult:
    application_id: ApplicationId
    status: ApplicationStatus
    version: int
    workflow_id: str | None


class ResubmitApplicationHandler:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        workflow_runner: WorkflowRunner | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._workflow_runner = workflow_runner

    async def handle(self, command: ResubmitApplicationCommand) -> ResubmitApplicationResult:
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

            application.transition_to(
                ApplicationStatus.DOCUMENT_PROCESSING,
                reason="applicant resubmitted with additional information",
                clock=self._clock,
            )
            workflow_id = application_workflow_id(
                tenant_id=command.tenant_id,
                application_id=command.application_id,
                version=application.version,
            )
            application.attach_workflow(workflow_id)
            await uow.applications.save(application)
            await uow.record_domain_events(application.pull_events())
            await uow.commit()

        if self._workflow_runner is not None:
            try:
                await self._workflow_runner.start_application_workflow(
                    workflow_id=workflow_id,
                    tenant_id=command.tenant_id,
                    application_id=command.application_id,
                    version=application.version,
                    starting_status=ApplicationStatus.DOCUMENT_PROCESSING.value,
                )
            except Exception as exc:  # noqa: BLE001 - best-effort, see submit_application.py
                logger.error(
                    "resubmit_application.workflow_start_failed",
                    application_id=str(command.application_id),
                    workflow_id=workflow_id,
                    error=str(exc),
                )

        return ResubmitApplicationResult(
            application_id=application.application_id,
            status=application.status,
            version=application.version,
            workflow_id=workflow_id,
        )
