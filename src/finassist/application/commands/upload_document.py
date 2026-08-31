"""`UploadDocumentCommand`: `POST /applications/{application_id}/documents`.

Stores the file in the existing Phase-2 `ObjectStore`, records metadata (`applications.documents`)
in the same transaction as the outbox event, per invariant §5.7 (no dual-write). The object write
happens *inside* the transaction, after the idempotency key is reserved and before commit: if it
fails, the whole transaction rolls back (including the reservation), so a client retry with the
same idempotency key is safe. A successful object write followed by a transaction failure leaves
an orphaned object in the (immutable, versioned) store -- an accepted, non-corrupting leak, not a
correctness bug.
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.ports.document_repository import UploadedDocument
from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.object_store import ObjectStore
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.events import DocumentUploaded
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    DuplicateRequestError,
)
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId

_OPERATION_NAME = "upload_document"


@dataclass(frozen=True, slots=True)
class UploadDocumentCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    idempotency_key: str
    document_type: str
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class UploadDocumentResult:
    document_id: str
    application_id: ApplicationId
    object_key: str
    checksum_sha256: str


class UploadDocumentHandler:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        object_store: ObjectStore,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._object_store = object_store
        self._id_generator = id_generator
        self._clock = clock

    async def handle(self, command: UploadDocumentCommand) -> UploadDocumentResult:
        async with self._uow_factory.begin(tenant_id=command.tenant_id) as uow:
            reserved = await uow.reserve_idempotency_key(
                key=command.idempotency_key, operation_name=_OPERATION_NAME
            )
            if not reserved:
                raise DuplicateRequestError(_OPERATION_NAME, command.idempotency_key)

            application = await uow.applications.get(
                tenant_id=command.tenant_id, application_id=command.application_id
            )
            if application is None:
                raise ApplicationNotFoundError(str(command.application_id))

            document_id = self._id_generator.new_id()
            object_key = f"applications/{command.application_id}/{document_id}/{command.filename}"
            metadata = await self._object_store.put_object(
                tenant_id=command.tenant_id,
                key=object_key,
                data=command.data,
                content_type=command.content_type,
            )

            now = self._clock.now()
            await uow.documents.add(
                UploadedDocument(
                    document_id=document_id,
                    tenant_id=command.tenant_id,
                    application_id=command.application_id,
                    document_type=command.document_type,
                    object_key=object_key,
                    checksum_sha256=metadata.checksum_sha256,
                    size_bytes=metadata.size_bytes,
                    uploaded_at=now,
                )
            )
            await uow.record_domain_events(
                [
                    DocumentUploaded(
                        application_id=command.application_id,
                        tenant_id=command.tenant_id,
                        occurred_at=now,
                        document_id=document_id,
                        document_type=command.document_type,
                        object_key=object_key,
                    )
                ]
            )
            await uow.commit()

            return UploadDocumentResult(
                document_id=document_id,
                application_id=command.application_id,
                object_key=object_key,
                checksum_sha256=metadata.checksum_sha256,
            )
