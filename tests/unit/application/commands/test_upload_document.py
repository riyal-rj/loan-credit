from __future__ import annotations

import pytest

from finassist.application.commands.upload_document import (
    UploadDocumentCommand,
    UploadDocumentHandler,
)
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    DuplicateRequestError,
)
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import ApplicationId, TenantId, new_id

from ._fakes import FakeObjectStore, FakeUnitOfWorkFactory, FixedIdGenerator
from ._helpers import NOW, make_product, seed_application_at


@pytest.mark.asyncio
async def test_upload_stores_object_and_metadata_and_records_event() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.DOCUMENT_PROCESSING
    )
    object_store = FakeObjectStore()
    handler = UploadDocumentHandler(
        uow_factory=factory,
        object_store=object_store,
        id_generator=FixedIdGenerator(["doc-1"]),
        clock=FixedClock(NOW),
    )

    result = await handler.handle(
        UploadDocumentCommand(
            tenant_id=tenant_id,
            application_id=application_id,
            idempotency_key="k1",
            document_type="income_proof",
            filename="payslip.pdf",
            content_type="application/pdf",
            data=b"synthetic pdf bytes",
        )
    )

    assert result.document_id == "doc-1"
    assert object_store.objects[(str(tenant_id), result.object_key)] == b"synthetic pdf bytes"
    assert len(factory.store.documents) == 1
    assert factory.store.documents[0].document_type == "income_proof"
    assert any(
        type(event).__name__ == "DocumentUploaded" for event in factory.store.recorded_events
    )


@pytest.mark.asyncio
async def test_unknown_application_raises() -> None:
    factory = FakeUnitOfWorkFactory()
    handler = UploadDocumentHandler(
        uow_factory=factory,
        object_store=FakeObjectStore(),
        id_generator=FixedIdGenerator(["doc-1"]),
        clock=FixedClock(NOW),
    )

    with pytest.raises(ApplicationNotFoundError):
        await handler.handle(
            UploadDocumentCommand(
                tenant_id=TenantId(new_id()),
                application_id=ApplicationId(new_id()),
                idempotency_key="k1",
                document_type="income_proof",
                filename="payslip.pdf",
                content_type="application/pdf",
                data=b"bytes",
            )
        )


@pytest.mark.asyncio
async def test_retry_with_same_idempotency_key_raises_duplicate() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.DOCUMENT_PROCESSING
    )
    handler = UploadDocumentHandler(
        uow_factory=factory,
        object_store=FakeObjectStore(),
        id_generator=FixedIdGenerator(["doc-1"]),
        clock=FixedClock(NOW),
    )
    command = UploadDocumentCommand(
        tenant_id=tenant_id,
        application_id=application_id,
        idempotency_key="same-key",
        document_type="income_proof",
        filename="payslip.pdf",
        content_type="application/pdf",
        data=b"bytes",
    )

    await handler.handle(command)

    with pytest.raises(DuplicateRequestError):
        await handler.handle(command)
