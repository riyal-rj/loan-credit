from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finassist.application.commands.advance_document_processing import (
    AdvanceDocumentProcessingCommand,
    AdvanceDocumentProcessingHandler,
)
from finassist.application.ports.document_repository import UploadedDocument
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import TenantId, new_id

from ._fakes import FakeUnitOfWorkFactory
from ._helpers import NOW, make_product, seed_application_at


@pytest.mark.asyncio
async def test_at_least_one_document_reaches_human_review_via_verification() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.DOCUMENT_PROCESSING
    )
    factory.store.documents.append(
        UploadedDocument(
            document_id=new_id(),
            tenant_id=tenant_id,
            application_id=application_id,
            document_type="income_proof",
            object_key="applications/x/y/z.pdf",
            checksum_sha256="deadbeef",
            size_bytes=10,
            uploaded_at=datetime.now(UTC),
        )
    )
    handler = AdvanceDocumentProcessingHandler(uow_factory=factory, clock=FixedClock(NOW))

    result = await handler.handle(
        AdvanceDocumentProcessingCommand(
            tenant_id=tenant_id, application_id=application_id, idempotency_key="k1"
        )
    )

    assert result.document_count == 1
    assert result.status is ApplicationStatus.AWAITING_HUMAN_REVIEW
    entry = factory.store.review_queue_entries[(str(tenant_id), str(application_id))]
    assert entry.status == "pending"


@pytest.mark.asyncio
async def test_zero_documents_escalates_to_human_review() -> None:
    # No automated NEEDS_MORE_INFORMATION path exists (only a human, from AWAITING_HUMAN_REVIEW,
    # can decide that) -- a missing-document case escalates with an explanatory reason instead.
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.DOCUMENT_PROCESSING
    )
    handler = AdvanceDocumentProcessingHandler(uow_factory=factory, clock=FixedClock(NOW))

    result = await handler.handle(
        AdvanceDocumentProcessingCommand(
            tenant_id=tenant_id, application_id=application_id, idempotency_key="k1"
        )
    )

    assert result.document_count == 0
    assert result.status is ApplicationStatus.AWAITING_HUMAN_REVIEW
    entry = factory.store.review_queue_entries[(str(tenant_id), str(application_id))]
    assert entry.status == "pending"
