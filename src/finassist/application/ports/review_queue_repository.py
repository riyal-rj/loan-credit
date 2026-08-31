"""Port for the Phase-3 reviewer-queue stopgap (docs/adr/0011).

`ReviewQueueEntry` is a port-local value type, not a `finassist.domain.review` aggregate --
Phase 3 deliberately does not stand up a "human review" bounded context (assignment, claim, SLA,
segregation of duties are master instruction §8/§17 concerns, all Phase 7 scope). This is one row
per application-in-review, enough to drive `POST /internal/applications/{id}/review-decisions`
end to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from finassist.domain.shared.identifiers import ApplicationId, TenantId


@dataclass(frozen=True, slots=True)
class ReviewQueueEntry:
    application_id: ApplicationId
    tenant_id: TenantId
    entered_queue_at: datetime
    status: str
    decision: str | None = None
    reason: str | None = None
    reviewer_id: str | None = None
    decided_at: datetime | None = None


@runtime_checkable
class ReviewQueueRepository(Protocol):
    async def add(self, entry: ReviewQueueEntry) -> None: ...

    async def get(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> ReviewQueueEntry | None: ...

    async def mark_decided(
        self,
        *,
        tenant_id: TenantId,
        application_id: ApplicationId,
        decision: str,
        reason: str,
        reviewer_id: str | None,
        decided_at: datetime,
    ) -> None: ...
