"""Synthetic document byte generation.

Produces real, valid, minimal single-page PDFs (not text files renamed to `.pdf`) so the
object-storage lifecycle (Phase 2 scope) stores and retrieves genuine PDF byte streams. Actual
OCR/text extraction and document classification are Phase 4 scope (master instruction §15) --
this module only needs to produce *a real file of the claimed type*, not a parseable-by-OCR one.
"""

from __future__ import annotations

from services.synthetic_data.applicants import SyntheticApplicant
from services.synthetic_data.employer import SyntheticEmploymentRecord


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_minimal_pdf(title: str, lines: list[str]) -> bytes:
    """Build a minimal, valid, single-page PDF containing `lines` of Helvetica 12pt text."""
    content_lines = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    for i, line in enumerate(lines):
        if i > 0:
            content_lines.append("T*")
        content_lines.append(f"({_escape_pdf_text(line)}) Tj")
    content_lines.append("ET")
    content_stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(content_stream)).encode("ascii")
        + b" >>\nstream\n"
        + content_stream
        + b"\nendstream",
    ]

    buffer = bytearray()
    buffer += b"%PDF-1.4\n"
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(buffer))
        buffer += f"{i} 0 obj\n".encode("ascii")
        buffer += body
        buffer += b"\nendobj\n"

    xref_offset = len(buffer)
    object_count = len(objects) + 1
    buffer += f"xref\n0 {object_count}\n".encode("ascii")
    buffer += b"0000000000 65535 f \n"
    for offset in offsets:
        buffer += f"{offset:010d} 00000 n \n".encode("ascii")
    escaped_title = _escape_pdf_text(title)
    buffer += (
        f"trailer\n<< /Size {object_count} /Root 1 0 R "
        f"/Info << /Title ({escaped_title}) >> >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode("ascii")
    return bytes(buffer)


def generate_pay_stub_pdf(
    applicant: SyntheticApplicant, employment: SyntheticEmploymentRecord
) -> bytes:
    monthly_gross = employment.verified_annual_income / 12
    lines = [
        f"SYNTHETIC PAY STUB -- {employment.employer_name}",
        f"Employee: {applicant.given_name} {applicant.family_name}",
        f"Pay period: Monthly    Gross pay: ${monthly_gross:,.2f}",
        f"Tenure: {employment.tenure_months} months",
        "This is a synthetic document generated for demo/testing purposes only.",
    ]
    return build_minimal_pdf(title="Synthetic Pay Stub", lines=lines)


def generate_identity_document_pdf(applicant: SyntheticApplicant) -> bytes:
    lines = [
        "SYNTHETIC GOVERNMENT-ISSUED ID (DEMO ONLY)",
        f"Name: {applicant.given_name} {applicant.family_name}",
        f"Date of birth: {applicant.date_of_birth.isoformat()}",
        f"Address: {applicant.street_address}, {applicant.city}",
        f"Synthetic ID: {applicant.synthetic_id}",
        "This is a synthetic document generated for demo/testing purposes only.",
    ]
    return build_minimal_pdf(title="Synthetic Identity Document", lines=lines)
