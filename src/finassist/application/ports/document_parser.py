"""Port for OCR/text extraction (master instruction §15: "Keep OCR/text extraction, document
classification, fact extraction, and verification as separate stages"). This is the *text-layer*
stage only -- classification and fact extraction are separate ports
(`document_extractor.py`) that consume this one's output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PageText:
    page: int
    """1-indexed page number."""
    text: str


@runtime_checkable
class DocumentParser(Protocol):
    async def extract_text(self, *, data: bytes, content_type: str) -> list[PageText]:
        """Return per-page text. Raises `finassist.domain.documents.exceptions.
        UnsupportedDocumentTypeError` for a content type with no parser, `ExtractionFailedError`
        for a parseable-type file whose bytes are corrupt/unreadable."""
        ...
