"""Write-mostly port for the `Applicant` entity (see docs/adr/0009 decision 5: no full aggregate
repository yet -- an applicant is created alongside its first application and looked up by ID
only, never queried/matched independently until Phase 4 needs that)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from finassist.domain.applications.applicant import Applicant
from finassist.domain.shared.identifiers import ApplicantId, TenantId


@runtime_checkable
class ApplicantRepository(Protocol):
    async def add(self, applicant: Applicant) -> None: ...

    async def get(self, *, tenant_id: TenantId, applicant_id: ApplicantId) -> Applicant | None: ...
