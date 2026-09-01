"""Cross-source verification value types (master instruction §8 context 4 "Verification":
cross-source checks, contradiction, verification status, confidence, source system response).

A `VerificationCheck` compares one document-extracted fact against one external system's
response for the same fact -- never against another document's extraction, and never resolved
without evidence (§9 Verification Agent: "Resolve contradictions without evidence" is explicitly
forbidden). `INSUFFICIENT_EVIDENCE` is a first-class verdict, not a missing/null case: it is what
a check becomes when the fact it needs was never extracted (e.g. no identity document was
uploaded), and it is exactly the guardrail invariant §5.10 requires ("low confidence, ...
guardrail failures must route to human review") -- a Phase 4 check that can't run is not silently
skipped, it is recorded as unresolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VerificationVerdict(StrEnum):
    MATCHED = "MATCHED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class SourceSystem(StrEnum):
    MOCK_KYC = "MOCK_KYC"
    MOCK_EMPLOYER = "MOCK_EMPLOYER"
    MOCK_BUREAU = "MOCK_BUREAU"
    MOCK_CORE_BANKING = "MOCK_CORE_BANKING"


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    source_system: SourceSystem
    checked_fact_type: str
    declared_value: str | None
    external_value: str | None
    verdict: VerificationVerdict
    confidence: float
    detail: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence} must be in [0.0, 1.0]")
