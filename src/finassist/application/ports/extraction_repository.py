"""Port for persisting/reading one document's extraction results (master instruction §10.1
`documents` schema: `extraction_runs`, `extracted_facts`). One `add_run` call records the run and
every fact it found in one write, since a `process_document` command always produces both
together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from finassist.domain.documents.document_fact import DocumentClassification, ExtractedFact
from finassist.domain.shared.identifiers import ApplicationId, TenantId


@dataclass(frozen=True, slots=True)
class StoredFact:
    fact_id: str
    document_id: str
    run_id: str
    fact: ExtractedFact


@runtime_checkable
class ExtractionRepository(Protocol):
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
        """Record one extraction run and its facts (`len(fact_ids) == len(facts)`, positionally
        paired -- `fact_ids` come from the caller's `IdGenerator` so the repository stays free of
        ID-generation concerns, matching every other repository in this codebase)."""
        ...

    async def get_facts_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> list[StoredFact]:
        """Every fact extracted so far, across every document uploaded for this application."""
        ...
