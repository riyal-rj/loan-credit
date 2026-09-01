"""`StubFileSafetyScanner`: the `FileSafetyScanner` port's Phase 4 adapter.

Extension/MIME-signature/size/page-count/encryption checks are real -- these don't need a third-
party service, just correct code. The malware-signature check is a dev-only stub that always
reports clean, the same "dev-only, real adapter deferred" pattern as `SecretProvider`/
`AuthorizationProvider` (ADR-0005): a real ClamAV (or equivalent) integration is Phase 9 (security
hardening) scope, and this build never claims otherwise.
"""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from finassist.application.ports.file_safety import FileSafetyReport, FileSafetyScanner
from finassist.domain.documents.exceptions import (
    DocumentTooLargeError,
    ExtractionFailedError,
    PageLimitExceededError,
    UnsupportedDocumentTypeError,
)

_MAGIC_BYTES_BY_CONTENT_TYPE: dict[str, bytes] = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
}
_ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class StubFileSafetyScanner(FileSafetyScanner):
    def __init__(self, *, max_size_bytes: int, max_pages: int) -> None:
        self._max_size_bytes = max_size_bytes
        self._max_pages = max_pages

    async def scan(
        self, *, data: bytes, filename: str, declared_content_type: str
    ) -> FileSafetyReport:
        if len(data) > self._max_size_bytes:
            raise DocumentTooLargeError(len(data), self._max_size_bytes)

        extension = _extension_of(filename)
        expected_content_type = _ALLOWED_EXTENSIONS.get(extension)
        if expected_content_type is None:
            raise UnsupportedDocumentTypeError(declared_content_type)

        detected_content_type = _sniff_content_type(data)
        if detected_content_type != expected_content_type:
            # The declared extension/content-type must match what the bytes actually are --
            # never trust a client-supplied MIME type or file extension alone.
            raise UnsupportedDocumentTypeError(declared_content_type)

        page_count = 1
        if detected_content_type == "application/pdf":
            page_count = _pdf_page_count(data)
        if page_count > self._max_pages:
            raise PageLimitExceededError(page_count, self._max_pages)

        await self._malware_scan(data)

        return FileSafetyReport(detected_content_type=detected_content_type, page_count=page_count)

    async def _malware_scan(self, data: bytes) -> None:
        """Stub: always clean. See module docstring -- a real scanner is Phase 9 scope."""
        return None


def _extension_of(filename: str) -> str:
    _, _, suffix = filename.rpartition(".")
    return f".{suffix.lower()}" if suffix else ""


def _sniff_content_type(data: bytes) -> str | None:
    for content_type, magic in _MAGIC_BYTES_BY_CONTENT_TYPE.items():
        if data.startswith(magic):
            return content_type
    return None


def _pdf_page_count(data: bytes) -> int:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UnsupportedDocumentTypeError("application/pdf (encrypted)")
        return len(reader.pages)
    except PdfReadError as exc:
        raise ExtractionFailedError("unknown", f"unreadable PDF: {exc}") from exc
