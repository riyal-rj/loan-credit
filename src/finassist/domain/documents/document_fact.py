"""`ExtractedFact`: one fact pulled from a document by `DocumentExtractor` (master instruction
§15: "Store each fact with value, normalized value, type, confidence, page, ... extraction
method, extractor/model version, source checksum, and run ID").

`FactType` is deliberately narrow -- one entry per fact this build's regex-based extractor
(Phase 4) actually produces from the Phase 2 synthetic pay-stub/identity-document corpus. Adding a
document class in a later phase means adding fact types here, not inventing an untyped
`extra: dict[str, str]` escape hatch (master instruction §28: "generic database dictionaries
instead of a domain model" is a rejection criterion).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FactType(StrEnum):
    APPLICANT_GIVEN_NAME = "APPLICANT_GIVEN_NAME"
    APPLICANT_FAMILY_NAME = "APPLICANT_FAMILY_NAME"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    STREET_ADDRESS = "STREET_ADDRESS"
    CITY = "CITY"
    SYNTHETIC_ID = "SYNTHETIC_ID"
    EMPLOYER_NAME = "EMPLOYER_NAME"
    GROSS_MONTHLY_INCOME = "GROSS_MONTHLY_INCOME"
    TENURE_MONTHS = "TENURE_MONTHS"


class DocumentClassification(StrEnum):
    """The system's own classification of a document's content -- distinct from the free-text
    `document_type` the uploader declared at `POST /applications/{id}/documents` (Phase 3). The
    two are cross-checked, not assumed equal."""

    IDENTITY_DOCUMENT = "IDENTITY_DOCUMENT"
    INCOME_PROOF = "INCOME_PROOF"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExtractedFact:
    fact_type: FactType
    value: str
    normalized_value: str
    confidence: float
    page: int
    extraction_method: str
    extractor_version: str
    source_checksum: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence} must be in [0.0, 1.0]")
        if self.page < 1:
            raise ValueError("page must be at least 1")
