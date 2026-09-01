"""SQLAlchemy-backed `ExtractionRepository` adapter (Phase 4).

`add_run` flushes the `ExtractionRunRow` insert *before* adding the `ExtractedFactRow` rows that
reference it, rather than adding both and flushing once: a single combined flush let asyncpg's
"insertmanyvalues" batching for the (usually multi-row) `extracted_facts` insert execute before
the single-row `extraction_runs` insert, tripping `extracted_facts_run_id_fkey` -- a real bug this
project's own integration test caught (docs/adr/0012), not something `Session.add()` call order
alone protects against.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.application.ports.extraction_repository import ExtractionRepository, StoredFact
from finassist.domain.documents.document_fact import DocumentClassification, ExtractedFact, FactType
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.infrastructure.postgres.orm_models import ExtractedFactRow, ExtractionRunRow


def _row_to_stored_fact(row: ExtractedFactRow) -> StoredFact:
    return StoredFact(
        fact_id=row.fact_id,
        document_id=row.document_id,
        run_id=row.run_id,
        fact=ExtractedFact(
            fact_type=FactType(row.fact_type),
            value=row.value,
            normalized_value=row.normalized_value,
            confidence=row.confidence,
            page=row.page,
            extraction_method=row.extraction_method,
            extractor_version=row.extractor_version,
            source_checksum=row.source_checksum,
        ),
    )


class SqlAlchemyExtractionRepository(ExtractionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_run(
        self,
        *,
        run_id: str,
        tenant_id: TenantId,
        application_id: ApplicationId,
        document_id: str,
        classification: DocumentClassification,
        facts: list[ExtractedFact],
        fact_ids: list[str],
        completed_at: datetime,
    ) -> None:
        if len(facts) != len(fact_ids):
            raise ValueError("facts and fact_ids must be the same length")

        self._session.add(
            ExtractionRunRow(
                run_id=run_id,
                tenant_id=str(tenant_id),
                application_id=str(application_id),
                document_id=document_id,
                classification=classification.value,
                fact_count=len(facts),
                completed_at=completed_at,
            )
        )
        await self._session.flush()

        for fact_id, fact in zip(fact_ids, facts, strict=True):
            self._session.add(
                ExtractedFactRow(
                    fact_id=fact_id,
                    run_id=run_id,
                    tenant_id=str(tenant_id),
                    application_id=str(application_id),
                    document_id=document_id,
                    fact_type=fact.fact_type.value,
                    value=fact.value,
                    normalized_value=fact.normalized_value,
                    confidence=fact.confidence,
                    page=fact.page,
                    extraction_method=fact.extraction_method,
                    extractor_version=fact.extractor_version,
                    source_checksum=fact.source_checksum,
                    status="extracted",
                    created_at=completed_at,
                )
            )
        await self._session.flush()

    async def get_facts_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> list[StoredFact]:
        result = await self._session.execute(
            select(ExtractedFactRow).where(
                ExtractedFactRow.tenant_id == str(tenant_id),
                ExtractedFactRow.application_id == str(application_id),
            )
        )
        return [_row_to_stored_fact(row) for row in result.scalars().all()]
