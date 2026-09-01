"""`ProcessDocumentCommand`: invoked by `extract_document_facts_activity`
(`finassist.infrastructure.temporal.activities`) once per uploaded document, never directly by
the API.

Parse -> classify -> extract -> persist for one already-safety-checked, already-stored document
(file safety happens once, at upload time -- `UploadDocumentHandler`, Phase 3/4). An unparseable
or unrecognized document is not a hard failure here: it yields zero facts and a `DocumentClassifi
cation.UNKNOWN`/empty result, which the caller records as-is (master instruction §15: insufficient
evidence is a legitimate, reportable outcome, never papered over).
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.ports.document_extractor import DocumentExtractor
from finassist.application.ports.document_parser import DocumentParser
from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.object_store import ObjectStore
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.domain.applications.exceptions import DuplicateRequestError
from finassist.domain.documents.document_fact import DocumentClassification, ExtractedFact
from finassist.domain.documents.exceptions import (
    DocumentNotFoundError,
    ExtractionFailedError,
    UnsupportedDocumentTypeError,
)
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId

_OPERATION_NAME = "process_document"


@dataclass(frozen=True, slots=True)
class ProcessDocumentCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    document_id: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ProcessDocumentResult:
    document_id: str
    classification: DocumentClassification
    fact_count: int
    extraction_error: str | None
    """Set when parsing/extraction could not run at all (unsupported type, corrupt file) --
    distinct from "ran fine, found zero facts" (`extraction_error is None`, `fact_count == 0`)."""


class ProcessDocumentHandler:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        object_store: ObjectStore,
        document_parser: DocumentParser,
        document_extractor: DocumentExtractor,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._object_store = object_store
        self._document_parser = document_parser
        self._document_extractor = document_extractor
        self._id_generator = id_generator
        self._clock = clock

    async def handle(self, command: ProcessDocumentCommand) -> ProcessDocumentResult:
        async with self._uow_factory.begin(tenant_id=command.tenant_id) as uow:
            reserved = await uow.reserve_idempotency_key(
                key=command.idempotency_key, operation_name=_OPERATION_NAME
            )
            if not reserved:
                raise DuplicateRequestError(_OPERATION_NAME, command.idempotency_key)

            documents = await uow.documents.list_for_application(
                tenant_id=command.tenant_id, application_id=command.application_id
            )
            document = next((d for d in documents if d.document_id == command.document_id), None)
            if document is None:
                raise DocumentNotFoundError(command.document_id)

            metadata = await self._object_store.get_object_metadata(
                tenant_id=command.tenant_id, key=document.object_key
            )

            classification = DocumentClassification.UNKNOWN
            facts: list[ExtractedFact] = []
            extraction_error: str | None = None
            try:
                data = await self._object_store.get_object(
                    tenant_id=command.tenant_id, key=document.object_key
                )
                pages = await self._document_parser.extract_text(
                    data=data, content_type=metadata.content_type
                )
                classification = self._document_extractor.classify(pages=pages)
                facts = self._document_extractor.extract_facts(
                    pages=pages,
                    classification=classification,
                    source_checksum=document.checksum_sha256,
                )
            except (UnsupportedDocumentTypeError, ExtractionFailedError) as exc:
                extraction_error = str(exc)

            fact_ids = [self._id_generator.new_id() for _ in facts]
            await uow.extraction.add_run(
                run_id=self._id_generator.new_id(),
                tenant_id=command.tenant_id,
                application_id=command.application_id,
                document_id=command.document_id,
                classification=classification,
                facts=facts,
                fact_ids=fact_ids,
                completed_at=self._clock.now(),
            )
            await uow.commit()

            return ProcessDocumentResult(
                document_id=command.document_id,
                classification=classification,
                fact_count=len(facts),
                extraction_error=extraction_error,
            )
