"""`GetApplicationStatusQuery`: `GET /applications/{application_id}`.

Reads the strongly-consistent authoritative `applications` row via the same
`ApplicationRepository` port commands use -- *not* `applications.status_projection` (the Kafka
projection consumer's read model), which is eventually consistent by design and not yet exposed
via API (docs/adr/0011).
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.exceptions import ApplicationNotFoundError
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.identifiers import ApplicationId, TenantId


@dataclass(frozen=True, slots=True)
class GetApplicationStatusQuery:
    tenant_id: TenantId
    application_id: ApplicationId


@dataclass(frozen=True, slots=True)
class ApplicationStatusResult:
    application_id: ApplicationId
    status: ApplicationStatus
    version: int
    active_workflow_id: str | None


class GetApplicationStatusHandler:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def handle(self, query: GetApplicationStatusQuery) -> ApplicationStatusResult:
        async with self._uow_factory.begin(tenant_id=query.tenant_id) as uow:
            application = await uow.applications.get(
                tenant_id=query.tenant_id, application_id=query.application_id
            )
            if application is None:
                raise ApplicationNotFoundError(str(query.application_id))
            return ApplicationStatusResult(
                application_id=application.application_id,
                status=application.status,
                version=application.version,
                active_workflow_id=application.active_workflow_id,
            )
