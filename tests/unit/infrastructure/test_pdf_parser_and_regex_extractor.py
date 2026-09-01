"""Unit tests for the Phase 4 document-intelligence adapters against real synthetic PDFs
(`services/synthetic_data/documents.py`) -- no I/O beyond in-memory PDF parsing, fully
deterministic."""

from __future__ import annotations

import pytest
from services.synthetic_data.applicants import generate_applicant
from services.synthetic_data.documents import generate_identity_document_pdf, generate_pay_stub_pdf
from services.synthetic_data.employer import generate_employment_record

from finassist.application.ports.document_parser import PageText
from finassist.domain.documents.document_fact import DocumentClassification, ExtractedFact, FactType
from finassist.domain.documents.exceptions import UnsupportedDocumentTypeError
from finassist.infrastructure.documents.pdf_parser import PyPdfDocumentParser
from finassist.infrastructure.documents.regex_extractor import RegexDocumentExtractor

_SCENARIO = "NORMAL_ELIGIBLE"


def _facts_by_type(facts: list[ExtractedFact]) -> dict[FactType, str]:
    return {f.fact_type: f.normalized_value for f in facts}


@pytest.mark.asyncio
async def test_pdf_parser_extracts_pay_stub_text() -> None:
    applicant = generate_applicant(_SCENARIO, 0)
    employment = generate_employment_record(applicant, _SCENARIO, 0)
    pdf_bytes = generate_pay_stub_pdf(applicant, employment)

    pages = await PyPdfDocumentParser().extract_text(data=pdf_bytes, content_type="application/pdf")

    assert len(pages) == 1
    assert "SYNTHETIC PAY STUB" in pages[0].text
    assert applicant.employer_name in pages[0].text


@pytest.mark.asyncio
async def test_pdf_parser_rejects_unsupported_content_type() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        await PyPdfDocumentParser().extract_text(data=b"not a pdf", content_type="image/png")


def test_extractor_classifies_pay_stub_as_income_proof() -> None:
    extractor = RegexDocumentExtractor()
    pages = [PageText(page=1, text="SYNTHETIC PAY STUB -- Acme Inc.\nEmployee: Ada Lovelace")]
    assert extractor.classify(pages=pages) is DocumentClassification.INCOME_PROOF


def test_extractor_classifies_identity_document() -> None:
    extractor = RegexDocumentExtractor()
    pages = [
        PageText(page=1, text="SYNTHETIC GOVERNMENT-ISSUED ID (DEMO ONLY)\nName: Ada Lovelace")
    ]
    assert extractor.classify(pages=pages) is DocumentClassification.IDENTITY_DOCUMENT


def test_extractor_classifies_unknown_content_as_unknown() -> None:
    extractor = RegexDocumentExtractor()
    pages = [PageText(page=1, text="This document has nothing to do with underwriting.")]
    assert extractor.classify(pages=pages) is DocumentClassification.UNKNOWN
    facts = extractor.extract_facts(
        pages=pages, classification=DocumentClassification.UNKNOWN, source_checksum="x"
    )
    assert facts == []


@pytest.mark.asyncio
async def test_extracts_all_facts_from_a_real_pay_stub() -> None:
    applicant = generate_applicant(_SCENARIO, 1)
    employment = generate_employment_record(applicant, _SCENARIO, 1)
    pdf_bytes = generate_pay_stub_pdf(applicant, employment)
    pages = await PyPdfDocumentParser().extract_text(data=pdf_bytes, content_type="application/pdf")
    extractor = RegexDocumentExtractor()

    classification = extractor.classify(pages=pages)
    facts = extractor.extract_facts(
        pages=pages, classification=classification, source_checksum="abc123"
    )

    by_type = _facts_by_type(facts)
    assert by_type[FactType.EMPLOYER_NAME] == employment.employer_name
    expected_monthly_income = f"{employment.verified_annual_income / 12:.2f}"
    assert by_type[FactType.GROSS_MONTHLY_INCOME] == expected_monthly_income
    assert by_type[FactType.TENURE_MONTHS] == str(employment.tenure_months)
    assert all(f.confidence == 1.0 for f in facts)
    assert all(f.source_checksum == "abc123" for f in facts)
    assert all(f.extraction_method == "regex_pattern_match" for f in facts)


@pytest.mark.asyncio
async def test_extracts_all_facts_from_a_real_identity_document() -> None:
    applicant = generate_applicant(_SCENARIO, 2)
    pdf_bytes = generate_identity_document_pdf(applicant)
    pages = await PyPdfDocumentParser().extract_text(data=pdf_bytes, content_type="application/pdf")
    extractor = RegexDocumentExtractor()

    classification = extractor.classify(pages=pages)
    facts = extractor.extract_facts(
        pages=pages, classification=classification, source_checksum="def456"
    )

    by_type = _facts_by_type(facts)
    assert by_type[FactType.APPLICANT_GIVEN_NAME] == applicant.given_name.lower()
    assert by_type[FactType.APPLICANT_FAMILY_NAME] == applicant.family_name.lower()
    assert by_type[FactType.DATE_OF_BIRTH] == applicant.date_of_birth.isoformat()
    assert by_type[FactType.STREET_ADDRESS] == applicant.street_address
    assert by_type[FactType.CITY] == applicant.city
    assert by_type[FactType.SYNTHETIC_ID] == applicant.synthetic_id
