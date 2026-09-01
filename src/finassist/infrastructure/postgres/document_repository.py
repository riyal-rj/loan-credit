"""SQLAlchemy-backed `DocumentRepository` adapter (Phase 3)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.application.ports.document_repository import DocumentRepository, UploadedDocument
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.infrastructure.postgres.orm_models import DocumentRow


def _row_to_document(row: DocumentRow) -> UploadedDocument:
    return UploadedDocument(
        document_id=row.document_id,
        tenant_id=TenantId(row.tenant_id),
        application_id=ApplicationId(row.application_id),
        document_type=row.document_type,
        object_key=row.object_key,
        checksum_sha256=row.checksum_sha256,
        size_bytes=row.size_bytes,
        uploaded_at=row.uploaded_at,
    )


class SqlAlchemyDocumentRepository(DocumentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: UploadedDocument) -> None:
        self._session.add(
            DocumentRow(
                document_id=document.document_id,
                tenant_id=str(document.tenant_id),
                application_id=str(document.application_id),
                document_type=document.document_type,
                object_key=document.object_key,
                checksum_sha256=document.checksum_sha256,
                size_bytes=document.size_bytes,
                uploaded_at=document.uploaded_at,
            )
        )
        await self._session.flush()

    async def count_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(DocumentRow)
            .where(
                DocumentRow.tenant_id == str(tenant_id),
                DocumentRow.application_id == str(application_id),
            )
        )
        return int(result.scalar_one())

    async def list_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> list[UploadedDocument]:
        result = await self._session.execute(
            select(DocumentRow)
            .where(
                DocumentRow.tenant_id == str(tenant_id),
                DocumentRow.application_id == str(application_id),
            )
            .order_by(DocumentRow.uploaded_at)
        )
        return [_row_to_document(row) for row in result.scalars().all()]
