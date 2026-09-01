"""SQLAlchemy-backed `VerificationRepository` adapter (Phase 4).

`add_run` flushes after each row group that a later group references (run -> checks ->
contradictions/snapshots) instead of adding everything and flushing once: a single combined flush
let asyncpg's "insertmanyvalues" batching for a multi-row child insert execute before its parent
row's insert, tripping the FK constraint -- the same real bug `ExtractionRepository.add_run` hit
and documents (docs/adr/0012), applied here defensively before it could reoccur.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.application.ports.verification_repository import (
    ExternalResponseSnapshot,
    VerificationRepository,
)
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.domain.verification.contradiction import (
    SourceSystem,
    VerificationCheck,
    VerificationVerdict,
)
from finassist.infrastructure.postgres.orm_models import (
    ContradictionRow,
    ExternalResponseSnapshotRow,
    VerificationCheckRow,
    VerificationRunRow,
)


def _row_to_check(row: VerificationCheckRow) -> VerificationCheck:
    return VerificationCheck(
        source_system=SourceSystem(row.source_system),
        checked_fact_type=row.checked_fact_type,
        declared_value=row.declared_value,
        external_value=row.external_value,
        verdict=VerificationVerdict(row.verdict),
        confidence=row.confidence,
        detail=row.detail,
    )


class SqlAlchemyVerificationRepository(VerificationRepository):
    def __init__(self, session: AsyncSession, new_id: Callable[[], str]) -> None:
        self._session = session
        self._new_id = new_id

    async def add_run(
        self,
        *,
        run_id: str,
        tenant_id: TenantId,
        application_id: ApplicationId,
        checks: list[VerificationCheck],
        check_ids: list[str],
        snapshots: list[ExternalResponseSnapshot],
        snapshot_ids: list[str],
        completed_at: datetime,
    ) -> None:
        if len(checks) != len(check_ids):
            raise ValueError("checks and check_ids must be the same length")
        if len(snapshots) != len(snapshot_ids):
            raise ValueError("snapshots and snapshot_ids must be the same length")

        contradiction_count = sum(
            1 for check in checks if check.verdict is VerificationVerdict.CONTRADICTED
        )
        self._session.add(
            VerificationRunRow(
                run_id=run_id,
                tenant_id=str(tenant_id),
                application_id=str(application_id),
                check_count=len(checks),
                contradiction_count=contradiction_count,
                completed_at=completed_at,
            )
        )
        await self._session.flush()

        for check_id, check in zip(check_ids, checks, strict=True):
            self._session.add(
                VerificationCheckRow(
                    check_id=check_id,
                    run_id=run_id,
                    tenant_id=str(tenant_id),
                    application_id=str(application_id),
                    source_system=check.source_system.value,
                    checked_fact_type=check.checked_fact_type,
                    declared_value=check.declared_value,
                    external_value=check.external_value,
                    verdict=check.verdict.value,
                    confidence=check.confidence,
                    detail=check.detail,
                    created_at=completed_at,
                )
            )
        for snapshot_id, snapshot in zip(snapshot_ids, snapshots, strict=True):
            self._session.add(
                ExternalResponseSnapshotRow(
                    snapshot_id=snapshot_id,
                    run_id=run_id,
                    tenant_id=str(tenant_id),
                    application_id=str(application_id),
                    source_system=snapshot.source_system.value,
                    response_payload=snapshot.response_payload,
                    captured_at=completed_at,
                )
            )
        await self._session.flush()

        for check_id, check in zip(check_ids, checks, strict=True):
            if check.verdict is VerificationVerdict.CONTRADICTED:
                self._session.add(
                    ContradictionRow(
                        contradiction_id=self._new_id(),
                        check_id=check_id,
                        tenant_id=str(tenant_id),
                        application_id=str(application_id),
                        source_system=check.source_system.value,
                        checked_fact_type=check.checked_fact_type,
                        detail=check.detail,
                        created_at=completed_at,
                    )
                )
        await self._session.flush()

    async def get_checks_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> list[VerificationCheck]:
        result = await self._session.execute(
            select(VerificationCheckRow).where(
                VerificationCheckRow.tenant_id == str(tenant_id),
                VerificationCheckRow.application_id == str(application_id),
            )
        )
        return [_row_to_check(row) for row in result.scalars().all()]
