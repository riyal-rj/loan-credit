"""Synthetic KYC (identity verification) result generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from services.synthetic_data.applicants import SyntheticApplicant
from services.synthetic_data.rng import rng_for


class KycStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 # nosec B105 -- a verification outcome, not a credential
    FAIL = "FAIL"
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class SyntheticKycResult:
    applicant_synthetic_id: str
    status: KycStatus
    name_match_score: float
    address_match_score: float
    date_of_birth_match: bool
    reference_id: str


def generate_kyc_result(
    applicant: SyntheticApplicant, scenario_id: str, index: int = 0
) -> SyntheticKycResult:
    rng = rng_for(f"kyc:{scenario_id}:{applicant.synthetic_id}", index)
    reference_id = f"KYC-{rng.randint(100_000, 999_999)}"

    if scenario_id == "KYC_IDENTITY_MISMATCH":
        return SyntheticKycResult(
            applicant_synthetic_id=applicant.synthetic_id,
            status=KycStatus.FAIL,
            name_match_score=rng.uniform(0.2, 0.5),
            address_match_score=rng.uniform(0.1, 0.4),
            date_of_birth_match=False,
            reference_id=reference_id,
        )

    if scenario_id == "DUPLICATE_IDENTITY":
        return SyntheticKycResult(
            applicant_synthetic_id=applicant.synthetic_id,
            status=KycStatus.REVIEW,
            name_match_score=rng.uniform(0.9, 1.0),
            address_match_score=rng.uniform(0.9, 1.0),
            date_of_birth_match=True,
            reference_id=reference_id,
        )

    return SyntheticKycResult(
        applicant_synthetic_id=applicant.synthetic_id,
        status=KycStatus.PASS,
        name_match_score=rng.uniform(0.92, 1.0),
        address_match_score=rng.uniform(0.9, 1.0),
        date_of_birth_match=True,
        reference_id=reference_id,
    )
