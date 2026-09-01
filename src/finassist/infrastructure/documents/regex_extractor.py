"""`RegexDocumentExtractor`: the `DocumentExtractor` port's Phase 4 adapter -- deterministic
pattern matching against the known layout `services/synthetic_data/documents.py` generates.

This is explicitly *not* general-purpose document understanding (docs/adr/0012): every pattern
here is tuned to one synthetic template. `confidence=1.0` on a match is honest, not optimistic --
there is no probabilistic uncertainty in a regex match the way there is in real OCR/NLP extraction,
so representing it as anything less than 1.0 would be manufacturing false uncertainty. A document
that doesn't match any known template classifies as `UNKNOWN` and yields zero facts (never a
fabricated guess) -- Phase 6's real extraction model is a drop-in replacement for this file alone.
"""

from __future__ import annotations

import contextlib
import re
from datetime import date

from finassist.application.ports.document_extractor import DocumentExtractor
from finassist.application.ports.document_parser import PageText
from finassist.domain.documents.document_fact import DocumentClassification, ExtractedFact, FactType

_EXTRACTOR_VERSION = "regex-v1"

_PAY_STUB_MARKER = "SYNTHETIC PAY STUB"
_IDENTITY_DOCUMENT_MARKER = "GOVERNMENT-ISSUED ID"

_EMPLOYER_NAME_RE = re.compile(r"SYNTHETIC PAY STUB\s*--\s*(.+)")
_EMPLOYEE_NAME_RE = re.compile(r"Employee:\s*(\S+)\s+(\S+)")
_GROSS_PAY_RE = re.compile(r"Gross pay:\s*\$([\d,]+\.\d{2})")
_TENURE_RE = re.compile(r"Tenure:\s*(\d+)\s*months")

_IDENTITY_NAME_RE = re.compile(r"Name:\s*(\S+)\s+(\S+)")
_DATE_OF_BIRTH_RE = re.compile(r"Date of birth:\s*(\d{4}-\d{2}-\d{2})")
_ADDRESS_RE = re.compile(r"Address:\s*(.+),\s*(.+)")
_SYNTHETIC_ID_RE = re.compile(r"Synthetic ID:\s*([\w-]+)")


def _find_page(pages: list[PageText], pattern: re.Pattern[str]) -> tuple[int, re.Match[str]] | None:
    for page in pages:
        match = pattern.search(page.text)
        if match is not None:
            return page.page, match
    return None


def _fact(
    fact_type: FactType, value: str, normalized_value: str, page: int, source_checksum: str
) -> ExtractedFact:
    return ExtractedFact(
        fact_type=fact_type,
        value=value,
        normalized_value=normalized_value,
        confidence=1.0,
        page=page,
        extraction_method="regex_pattern_match",
        extractor_version=_EXTRACTOR_VERSION,
        source_checksum=source_checksum,
    )


class RegexDocumentExtractor(DocumentExtractor):
    def classify(self, *, pages: list[PageText]) -> DocumentClassification:
        joined = "\n".join(page.text for page in pages)
        if _PAY_STUB_MARKER in joined:
            return DocumentClassification.INCOME_PROOF
        if _IDENTITY_DOCUMENT_MARKER in joined:
            return DocumentClassification.IDENTITY_DOCUMENT
        return DocumentClassification.UNKNOWN

    def extract_facts(
        self,
        *,
        pages: list[PageText],
        classification: DocumentClassification,
        source_checksum: str,
    ) -> list[ExtractedFact]:
        if classification is DocumentClassification.INCOME_PROOF:
            return self._extract_income_proof_facts(pages, source_checksum)
        if classification is DocumentClassification.IDENTITY_DOCUMENT:
            return self._extract_identity_document_facts(pages, source_checksum)
        return []

    def _extract_income_proof_facts(
        self, pages: list[PageText], source_checksum: str
    ) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []

        if (found := _find_page(pages, _EMPLOYER_NAME_RE)) is not None:
            page, match = found
            employer_name = match.group(1).strip()
            facts.append(
                _fact(FactType.EMPLOYER_NAME, employer_name, employer_name, page, source_checksum)
            )

        if (found := _find_page(pages, _GROSS_PAY_RE)) is not None:
            page, match = found
            raw = match.group(1)
            facts.append(
                _fact(
                    FactType.GROSS_MONTHLY_INCOME,
                    raw,
                    raw.replace(",", ""),
                    page,
                    source_checksum,
                )
            )

        if (found := _find_page(pages, _TENURE_RE)) is not None:
            page, match = found
            months = match.group(1)
            facts.append(_fact(FactType.TENURE_MONTHS, months, months, page, source_checksum))

        return facts

    def _extract_identity_document_facts(
        self, pages: list[PageText], source_checksum: str
    ) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []

        if (found := _find_page(pages, _IDENTITY_NAME_RE)) is not None:
            page, match = found
            given_name, family_name = match.group(1), match.group(2)
            facts.append(
                _fact(
                    FactType.APPLICANT_GIVEN_NAME,
                    given_name,
                    given_name.lower(),
                    page,
                    source_checksum,
                )
            )
            facts.append(
                _fact(
                    FactType.APPLICANT_FAMILY_NAME,
                    family_name,
                    family_name.lower(),
                    page,
                    source_checksum,
                )
            )

        if (found := _find_page(pages, _DATE_OF_BIRTH_RE)) is not None:
            page, match = found
            raw = match.group(1)
            normalized = raw
            with contextlib.suppress(ValueError):
                normalized = date.fromisoformat(raw).isoformat()
            facts.append(_fact(FactType.DATE_OF_BIRTH, raw, normalized, page, source_checksum))

        if (found := _find_page(pages, _ADDRESS_RE)) is not None:
            page, match = found
            street, city = match.group(1).strip(), match.group(2).strip()
            facts.append(_fact(FactType.STREET_ADDRESS, street, street, page, source_checksum))
            facts.append(_fact(FactType.CITY, city, city, page, source_checksum))

        if (found := _find_page(pages, _SYNTHETIC_ID_RE)) is not None:
            page, match = found
            synthetic_id = match.group(1)
            facts.append(
                _fact(FactType.SYNTHETIC_ID, synthetic_id, synthetic_id, page, source_checksum)
            )

        return facts
