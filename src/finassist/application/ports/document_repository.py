"""Port for the document-upload metadata written by `UploadDocumentHandler` (Phase 3).

`UploadedDocument` is a port-local value type, not a `finassist.domain` aggregate -- the same
choice `object_store.py` makes for `ObjectMetadata`. Real document intelligence (pages,
extraction, provenance, `finassist.domain.documents`) is Phase 4 scope; this record only proves
"a file was uploaded and stored for this application," which is all `check_required_documents_
activity` (Phase 3's workflow) needs to know.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from finassist.domain.shared.identifiers import ApplicationId, TenantId


@dataclass(frozen=True, slots=True)
class UploadedDocument:
    document_id: str
    tenant_id: TenantId
    application_id: ApplicationId
    document_type: str
    object_key: str
    checksum_sha256: str
    size_bytes: int
    uploaded_at: datetime


@runtime_checkable
class DocumentRepository(Protocol):
    async def add(self, document: UploadedDocument) -> None: ...

    async def count_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> int:
        """Count of documents uploaded for this application. Used by the workflow's
        document-presence gate, not as a substitute for Phase 4's real document classification."""
        ...
