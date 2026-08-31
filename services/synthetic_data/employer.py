"""Synthetic employment verification generation."""

from __future__ import annotations

from dataclasses import dataclass

from services.synthetic_data.applicants import SyntheticApplicant
from services.synthetic_data.rng import rng_for


@dataclass(frozen=True, slots=True)
class SyntheticEmploymentRecord:
    applicant_synthetic_id: str
    employer_name: str
    is_employment_confirmed: bool
    verified_annual_income: int
    tenure_months: int


def generate_employment_record(
    applicant: SyntheticApplicant, scenario_id: str, index: int = 0
) -> SyntheticEmploymentRecord:
    rng = rng_for(f"employer:{scenario_id}:{applicant.synthetic_id}", index)

    if scenario_id == "EMPLOYER_VERIFICATION_MISMATCH":
        return SyntheticEmploymentRecord(
            applicant_synthetic_id=applicant.synthetic_id,
            employer_name=applicant.employer_name,
            is_employment_confirmed=True,
            verified_annual_income=int(applicant.declared_annual_income * rng.uniform(0.4, 0.7)),
            tenure_months=rng.randint(1, 5),
        )

    return SyntheticEmploymentRecord(
        applicant_synthetic_id=applicant.synthetic_id,
        employer_name=applicant.employer_name,
        is_employment_confirmed=True,
        verified_annual_income=int(applicant.declared_annual_income * rng.uniform(0.95, 1.05)),
        tenure_months=rng.randint(12, 96),
    )
