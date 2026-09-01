from __future__ import annotations

import pytest
from services.synthetic_data.applicants import generate_applicant
from services.synthetic_data.documents import generate_pay_stub_pdf
from services.synthetic_data.employer import generate_employment_record

from finassist.application.commands.process_document import (
    ProcessDocumentCommand,
    ProcessDocumentHandler,
)
from finassist.application.ports.document_repository import UploadedDocument
from finassist.domain.applications.exceptions import DuplicateRequestError
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.documents.document_fact import DocumentClassification
from finassist.domain.documents.exceptions import DocumentNotFoundError
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import TenantId, new_id
from finassist.infrastructure.documents.pdf_parser import PyPdfDocumentParser
from finassist.infrastructure.documents.regex_extractor import RegexDocumentExtractor

from ._fakes import FakeObjectStore, FakeUnitOfWorkFactory, FixedIdGenerator
from ._helpers import NOW, make_product, seed_application_at


def _handler(
    uow_factory: FakeUnitOfWorkFactory, object_store: FakeObjectStore
) -> ProcessDocumentHandler:
    return ProcessDocumentHandler(
        uow_factory=uow_factory,
        object_store=object_store,
        document_parser=PyPdfDocumentParser(),
        document_extractor=RegexDocumentExtractor(),
        id_generator=FixedIdGenerator(["run-1", "fact-1", "fact-2", "fact-3"]),
        clock=FixedClock(NOW),
    )


@pytest.mark.asyncio
async def test_processes_a_real_pay_stub_and_stores_facts() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.DOCUMENT_PROCESSING
    )
    applicant = generate_applicant("NORMAL_ELIGIBLE", 0)
    employment = generate_employment_record(applicant, "NORMAL_ELIGIBLE", 0)
    pdf_bytes = generate_pay_stub_pdf(applicant, employment)

    object_store = FakeObjectStore()
    await object_store.put_object(
        tenant_id=tenant_id, key="applications/x/doc-1/paystub.pdf", data=pdf_bytes,
        content_type="application/pdf",
    )
    document_id = "doc-1"
    factory.store.documents.append(
        UploadedDocument(
            document_id=document_id,
            tenant_id=tenant_id,
            application_id=application_id,
            document_type="income_proof",
            object_key="applications/x/doc-1/paystub.pdf",
            checksum_sha256="irrelevant-for-this-test",
            size_bytes=len(pdf_bytes),
            uploaded_at=NOW,
        )
    )

    handler = _handler(factory, object_store)
    result = await handler.handle(
        ProcessDocumentCommand(
            tenant_id=tenant_id,
            application_id=application_id,
            document_id=document_id,
            idempotency_key="k1",
        )
    )

    assert result.classification is DocumentClassification.INCOME_PROOF
    assert result.fact_count == 3
    assert result.extraction_error is None
    assert len(factory.store.extracted_facts) == 3


@pytest.mark.asyncio
async def test_unknown_document_raises() -> None:
    tenant_id = TenantId(new_id())
    product = make_product()
    factory = FakeUnitOfWorkFactory(products=[product])
    application_id = await seed_application_at(
        factory, tenant_id=tenant_id, product=product, status=ApplicationStatus.DOCUMENT_PROCESSING
    )
    handler = _handler(factory, FakeObjectStore())

    with pytest.raises(DocumentNotFoundError):
        await handler.handle(
            ProcessDocumentCommand(
                tenant_id=tenant_id,
                application_id=application_id,
                document_id="does-not-exist",
                idempotency_key="k1",
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
    applicant = generate_applicant("NORMAL_ELIGIBLE", 3)
    employment = generate_employment_record(applicant, "NORMAL_ELIGIBLE", 3)
    pdf_bytes = generate_pay_stub_pdf(applicant, employment)
    object_store = FakeObjectStore()
    await object_store.put_object(
        tenant_id=tenant_id, key="applications/x/doc-1/paystub.pdf", data=pdf_bytes,
        content_type="application/pdf",
    )
    factory.store.documents.append(
        UploadedDocument(
            document_id="doc-1",
            tenant_id=tenant_id,
            application_id=application_id,
            document_type="income_proof",
            object_key="applications/x/doc-1/paystub.pdf",
            checksum_sha256="x",
            size_bytes=len(pdf_bytes),
            uploaded_at=NOW,
        )
    )
    handler = _handler(factory, object_store)
    command = ProcessDocumentCommand(
        tenant_id=tenant_id,
        application_id=application_id,
        document_id="doc-1",
        idempotency_key="same-key",
    )

    await handler.handle(command)

    with pytest.raises(DuplicateRequestError):
        await handler.handle(command)
