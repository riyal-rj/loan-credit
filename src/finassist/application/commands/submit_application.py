"""`SubmitApplicationCommand`: `POST /applications/{application_id}/submit`.

Idempotent the same way `create_application` is (docs: same idempotency-key reservation
mechanism), so a client retry after a timed-out response cannot double-submit a case. Phase 3
additionally starts the `ApplicationWorkflow` execution that will drive this case through intake,
document, and human-review activities (docs/adr/0002/0011).
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

_OPERATION_NAME = "submit_application"

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SubmitApplicationCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SubmitApplicationResult:
    application_id: ApplicationId
    status: ApplicationStatus
    version: int
    workflow_id: str | None


class SubmitApplicationHandler:
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

    async def handle(self, command: SubmitApplicationCommand) -> SubmitApplicationResult:
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

            application.submit(clock=self._clock)
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
                    starting_status=ApplicationStatus.SUBMITTED.value,
                )
            except Exception as exc:  # noqa: BLE001 - best-effort: the domain write already
                # committed above; a failure here is a missed workflow start, not a failed
                # submission (docs/adr/0011 "workflow start is best-effort, not
                # outbox-guaranteed"). Logged loudly so it is operationally visible.
                logger.error(
                    "submit_application.workflow_start_failed",
                    application_id=str(command.application_id),
                    workflow_id=workflow_id,
                    error=str(exc),
                )

        return SubmitApplicationResult(
            application_id=application.application_id,
            status=application.status,
            version=application.version,
            workflow_id=workflow_id,
        )
