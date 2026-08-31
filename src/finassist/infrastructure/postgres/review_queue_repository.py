"""SQLAlchemy-backed `ReviewQueueRepository` adapter -- the Phase-3 reviewer-queue stopgap
(docs/adr/0011)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from finassist.application.ports.review_queue_repository import (
    ReviewQueueEntry,
    ReviewQueueRepository,
)
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.infrastructure.postgres.orm_models import ReviewQueueEntryRow


def _row_to_entry(row: ReviewQueueEntryRow) -> ReviewQueueEntry:
    return ReviewQueueEntry(
        application_id=ApplicationId(row.application_id),
        tenant_id=TenantId(row.tenant_id),
        entered_queue_at=row.entered_queue_at,
        status=row.status,
        decision=row.decision,
        reason=row.reason,
        reviewer_id=row.reviewer_id,
        decided_at=row.decided_at,
    )


class SqlAlchemyReviewQueueRepository(ReviewQueueRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: ReviewQueueEntry) -> None:
        self._session.add(
            ReviewQueueEntryRow(
                application_id=str(entry.application_id),
                tenant_id=str(entry.tenant_id),
                entered_queue_at=entry.entered_queue_at,
                status=entry.status,
                decision=entry.decision,
                reason=entry.reason,
                reviewer_id=entry.reviewer_id,
                decided_at=entry.decided_at,
            )
        )
        await self._session.flush()

    async def get(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> ReviewQueueEntry | None:
        row = await self._session.get(ReviewQueueEntryRow, str(application_id))
        if row is None or row.tenant_id != str(tenant_id):
            return None
        return _row_to_entry(row)

    async def mark_decided(
        self,
        *,
        tenant_id: TenantId,
        application_id: ApplicationId,
        decision: str,
        reason: str,
        reviewer_id: str | None,
        decided_at: datetime,
    ) -> None:
        row = await self._session.get(ReviewQueueEntryRow, str(application_id))
        if row is None or row.tenant_id != str(tenant_id):
            raise LookupError(
                f"no review queue entry for application {application_id} to mark decided"
            )
        row.status = "decided"
        row.decision = decision
        row.reason = reason
        row.reviewer_id = reviewer_id
        row.decided_at = decided_at
        await self._session.flush()
