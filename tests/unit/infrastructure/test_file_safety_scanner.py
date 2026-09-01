"""Unit tests for `StubFileSafetyScanner` (Phase 4). Uses a real synthetic PDF for the happy
path and hand-built byte prefixes for the negative cases -- no I/O."""

from __future__ import annotations

import pytest
from services.synthetic_data.applicants import generate_applicant
from services.synthetic_data.documents import generate_identity_document_pdf

from finassist.domain.documents.exceptions import (
    DocumentTooLargeError,
    UnsupportedDocumentTypeError,
)
from finassist.infrastructure.documents.file_safety_scanner import StubFileSafetyScanner

_PDF_BYTES = generate_identity_document_pdf(generate_applicant("NORMAL_ELIGIBLE", 0))


def _scanner(*, max_size_bytes: int = 10_000, max_pages: int = 20) -> StubFileSafetyScanner:
    return StubFileSafetyScanner(max_size_bytes=max_size_bytes, max_pages=max_pages)


@pytest.mark.asyncio
async def test_accepts_a_real_pdf() -> None:
    report = await _scanner().scan(
        data=_PDF_BYTES, filename="id.pdf", declared_content_type="application/pdf"
    )
    assert report.detected_content_type == "application/pdf"
    assert report.page_count == 1


@pytest.mark.asyncio
async def test_rejects_oversized_file() -> None:
    with pytest.raises(DocumentTooLargeError):
        await _scanner(max_size_bytes=10).scan(
            data=_PDF_BYTES, filename="id.pdf", declared_content_type="application/pdf"
        )


@pytest.mark.asyncio
async def test_rejects_unrecognized_extension() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        await _scanner().scan(
            data=_PDF_BYTES, filename="id.exe", declared_content_type="application/pdf"
        )


@pytest.mark.asyncio
async def test_rejects_content_that_does_not_match_declared_extension() -> None:
    # A .pdf filename whose bytes are not actually a PDF -- never trust the extension alone.
    with pytest.raises(UnsupportedDocumentTypeError):
        await _scanner().scan(
            data=b"this is plain text, not a pdf",
            filename="id.pdf",
            declared_content_type="application/pdf",
        )


@pytest.mark.asyncio
async def test_accepts_a_real_png_by_magic_bytes() -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    report = await _scanner().scan(
        data=png_bytes, filename="photo.png", declared_content_type="image/png"
    )
    assert report.detected_content_type == "image/png"
    assert report.page_count == 1
