"""`PyPdfDocumentParser`: the `DocumentParser` port's Phase 4 adapter -- text-layer extraction via
`pypdf`, a real, maintained parsing library (not the hand-rolled writer `services/synthetic_data/
documents.py` uses to *produce* PDFs -- reading and writing are different problems).

Image content types have no parser yet (master instruction §15's "clear extension contract":
`StubFileSafetyScanner` already accepts PNG/JPEG at upload so a later phase adding real OCR is a
parser addition, not a validation-layer change) -- `extract_text` raises
`UnsupportedDocumentTypeError` for them rather than silently returning no text.
"""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from finassist.application.ports.document_parser import DocumentParser, PageText
from finassist.domain.documents.exceptions import (
    ExtractionFailedError,
    UnsupportedDocumentTypeError,
)

_SUPPORTED_CONTENT_TYPES = frozenset({"application/pdf"})


class PyPdfDocumentParser(DocumentParser):
    async def extract_text(self, *, data: bytes, content_type: str) -> list[PageText]:
        if content_type not in _SUPPORTED_CONTENT_TYPES:
            raise UnsupportedDocumentTypeError(content_type)
        try:
            reader = PdfReader(io.BytesIO(data))
            return [
                PageText(page=index, text=page.extract_text())
                for index, page in enumerate(reader.pages, start=1)
            ]
        except PdfReadError as exc:
            raise ExtractionFailedError("unknown", f"unreadable PDF: {exc}") from exc
