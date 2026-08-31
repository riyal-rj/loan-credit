"""`SubmitApplicationCommand`: `POST /applications/{application_id}/submit`.

Idempotent the same way `create_application` is (docs: same idempotency-key reservation
mechanism), so a client retry after a timed-out response cannot double-submit a case.
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    DuplicateRequestError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId

_OPERATION_NAME = "submit_application"


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


class SubmitApplicationHandler:
    def __init__(self, *, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

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
            await uow.applications.save(application)
            await uow.record_domain_events(application.pull_events())
            await uow.commit()

            return SubmitApplicationResult(
                application_id=application.application_id,
                status=application.status,
                version=application.version,
            )
