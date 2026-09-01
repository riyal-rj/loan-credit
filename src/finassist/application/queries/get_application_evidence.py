"""`GetApplicationEvidenceQuery`: `GET /applications/{application_id}/evidence` (master
instruction §11's minimum API list). Returns extracted facts + verification verdicts with
citations -- the data a reviewer needs; the side-by-side rendering of it is Phase 7's UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.ports.extraction_repository import StoredFact
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.exceptions import ApplicationNotFoundError
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.domain.verification.contradiction import VerificationCheck


@dataclass(frozen=True, slots=True)
class GetApplicationEvidenceQuery:
    tenant_id: TenantId
    application_id: ApplicationId


@dataclass(frozen=True, slots=True)
class ApplicationEvidenceResult:
    application_id: ApplicationId
    facts: list[StoredFact]
    verification_checks: list[VerificationCheck]


class GetApplicationEvidenceHandler:
    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def handle(self, query: GetApplicationEvidenceQuery) -> ApplicationEvidenceResult:
        async with self._uow_factory.begin(tenant_id=query.tenant_id) as uow:
            application = await uow.applications.get(
                tenant_id=query.tenant_id, application_id=query.application_id
            )
            if application is None:
                raise ApplicationNotFoundError(str(query.application_id))
            facts = await uow.extraction.get_facts_for_application(
                tenant_id=query.tenant_id, application_id=query.application_id
            )
            checks = await uow.verification.get_checks_for_application(
                tenant_id=query.tenant_id, application_id=query.application_id
            )
            return ApplicationEvidenceResult(
                application_id=query.application_id, facts=facts, verification_checks=checks
            )
