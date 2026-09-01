"""Port for file-safety validation before a document is parsed (master instruction §15:
"Validate extension, MIME signature, file size, page count, encryption status, decompression
limits, and malware scan before processing").

Raises a specific typed exception per failure reason (mirrors `domain.applications.exceptions`'
one-exception-per-reason style) rather than returning a generic pass/fail result, so a caller can
map each to a distinct problem-details code instead of parsing a rejection-reason string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class FileSafetyReport:
    detected_content_type: str
    """MIME type detected from the file's magic bytes -- not trusted from the caller-declared
    `content_type`, which is why this is returned rather than merely validated against."""

    page_count: int


@runtime_checkable
class FileSafetyScanner(Protocol):
    async def scan(
        self, *, data: bytes, filename: str, declared_content_type: str
    ) -> FileSafetyReport:
        """Validate ``data`` end to end. Raises `finassist.domain.documents.exceptions.
        UnsupportedDocumentTypeError`/`DocumentTooLargeError`/`PageLimitExceededError`/
        `MalwareDetectedError` on the first failed check; returns a report on success."""
        ...
