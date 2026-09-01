"""Port for document classification + fact extraction -- the seam Phase 6 replaces with a real
extraction model (docs/adr/0012). `RegexDocumentExtractor` (Phase 4) implements this against the
known Phase 2 synthetic document corpus; nothing outside this port's boundary needs to change when
a later phase swaps the implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from finassist.application.ports.document_parser import PageText
from finassist.domain.documents.document_fact import DocumentClassification, ExtractedFact


@runtime_checkable
class DocumentExtractor(Protocol):
    def classify(self, *, pages: list[PageText]) -> DocumentClassification:
        """Determine the document's content class from its parsed text. Returns `UNKNOWN` rather
        than raising when the content doesn't match a recognized document class -- an
        unrecognized document is a legitimate, reportable outcome, not an error."""
        ...

    def extract_facts(
        self,
        *,
        pages: list[PageText],
        classification: DocumentClassification,
        source_checksum: str,
    ) -> list[ExtractedFact]:
        """Return every fact this extractor can find. An empty list is a legitimate result
        (master instruction §15: preserve/report insufficient evidence honestly, never fabricate
        a fact to fill a gap)."""
        ...
