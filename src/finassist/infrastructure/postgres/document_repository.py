"""SQLAlchemy-backed `DocumentRepository` adapter (Phase 3)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.application.ports.document_repository import DocumentRepository, UploadedDocument
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.infrastructure.postgres.orm_models import DocumentRow


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
