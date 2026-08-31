from __future__ import annotations

import re

from services.synthetic_data.applicants import generate_applicant
from services.synthetic_data.documents import (
    build_minimal_pdf,
    generate_identity_document_pdf,
    generate_pay_stub_pdf,
)
from services.synthetic_data.employer import generate_employment_record

_APPLICANT = generate_applicant("NORMAL_ELIGIBLE", 0)


def _assert_structurally_valid_pdf(pdf_bytes: bytes) -> None:
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert pdf_bytes.rstrip().endswith(b"%%EOF")

    text = pdf_bytes.decode("latin-1")
    xref_match = re.search(r"startxref\s+(\d+)\s+%%EOF", text)
    assert xref_match is not None
    xref_offset = int(xref_match.group(1))
    assert text[xref_offset : xref_offset + 4] == "xref"

    object_headers = list(re.finditer(r"(\d+) 0 obj", text))
    assert len(object_headers) >= 5
    for match in object_headers:
        object_number = int(match.group(1))
        offset = match.start()
        assert text[offset:].startswith(f"{object_number} 0 obj")


def test_build_minimal_pdf_is_structurally_valid() -> None:
    pdf_bytes = build_minimal_pdf(title="Test", lines=["line one", "line two"])
    _assert_structurally_valid_pdf(pdf_bytes)


def test_build_minimal_pdf_escapes_parentheses_and_backslashes() -> None:
    pdf_bytes = build_minimal_pdf(title="Test", lines=["a (b) c \\ d"])
    assert rb"a \(b\) c \\ d" in pdf_bytes


def test_pay_stub_pdf_is_valid_and_contains_employer_name() -> None:
    employment = generate_employment_record(_APPLICANT, "NORMAL_ELIGIBLE")
    pdf_bytes = generate_pay_stub_pdf(_APPLICANT, employment)
    _assert_structurally_valid_pdf(pdf_bytes)
    assert employment.employer_name.encode("latin-1") in pdf_bytes


def test_identity_document_pdf_is_valid_and_contains_applicant_name() -> None:
    pdf_bytes = generate_identity_document_pdf(_APPLICANT)
    _assert_structurally_valid_pdf(pdf_bytes)
    assert _APPLICANT.given_name.encode("latin-1") in pdf_bytes
    assert _APPLICANT.family_name.encode("latin-1") in pdf_bytes
