"""Domain exceptions for document intelligence (Phase 4). Mapped to RFC 9457 problem details in
`finassist.api.error_handling.problem_details`, same pattern as `domain.applications.exceptions`.
"""

from __future__ import annotations


class UnsupportedDocumentTypeError(ValueError):
    """Raised when a document's content type has no parser (master instruction §15: only PDF is
    supported this phase; images are validated at upload but rejected at parse time)."""

    def __init__(self, content_type: str) -> None:
        super().__init__(f"no document parser registered for content type {content_type!r}")
        self.content_type = content_type


class MalwareDetectedError(RuntimeError):
    """Raised by `FileSafetyScanner.scan` when a file fails the malware check."""

    def __init__(self, key: str) -> None:
        super().__init__(f"file {key!r} failed the malware scan")
        self.key = key


class DocumentTooLargeError(ValueError):
    def __init__(self, size_bytes: int, max_size_bytes: int) -> None:
        super().__init__(f"document is {size_bytes} bytes, exceeding the {max_size_bytes} limit")
        self.size_bytes = size_bytes
        self.max_size_bytes = max_size_bytes


class PageLimitExceededError(ValueError):
    def __init__(self, page_count: int, max_pages: int) -> None:
        super().__init__(f"document has {page_count} pages, exceeding the {max_pages} limit")
        self.page_count = page_count
        self.max_pages = max_pages


class DocumentNotFoundError(LookupError):
    def __init__(self, document_id: str) -> None:
        super().__init__(f"document {document_id} does not exist for this application")
        self.document_id = document_id


class ExtractionFailedError(RuntimeError):
    """Raised when parsing succeeds but extraction cannot proceed at all (e.g. an unparseable/
    corrupt PDF byte stream) -- distinct from "parsed fine, found zero facts," which is not an
    error (master instruction §15: preserve/report insufficient evidence honestly)."""

    def __init__(self, document_id: str, reason: str) -> None:
        super().__init__(f"extraction failed for document {document_id}: {reason}")
        self.document_id = document_id
