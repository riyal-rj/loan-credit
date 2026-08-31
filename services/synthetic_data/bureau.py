"""Synthetic credit bureau report generation."""

from __future__ import annotations

from dataclasses import dataclass, field

from services.synthetic_data.applicants import SyntheticApplicant
from services.synthetic_data.rng import rng_for


@dataclass(frozen=True, slots=True)
class Tradeline:
    account_type: str
    opened_years_ago: int
    balance: int
    credit_limit: int
    is_delinquent: bool


@dataclass(frozen=True, slots=True)
class SyntheticBureauReport:
    applicant_synthetic_id: str
    credit_score: int
    tradelines: tuple[Tradeline, ...] = field(default_factory=tuple)
    hard_inquiries_last_12_months: int = 0
    is_duplicate_identity_flag: bool = False


_ACCOUNT_TYPES = ("credit_card", "auto_loan", "installment_loan", "student_loan")


def generate_bureau_report(
    applicant: SyntheticApplicant, scenario_id: str, index: int = 0
) -> SyntheticBureauReport:
    rng = rng_for(f"bureau:{scenario_id}:{applicant.synthetic_id}", index)

    if scenario_id == "THIN_FILE_BUREAU":
        return SyntheticBureauReport(
            applicant_synthetic_id=applicant.synthetic_id,
            credit_score=rng.randint(580, 640),
            tradelines=(
                Tradeline(
                    account_type="credit_card",
                    opened_years_ago=1,
                    balance=rng.randint(200, 800),
                    credit_limit=1000,
                    is_delinquent=False,
                ),
            ),
            hard_inquiries_last_12_months=rng.randint(0, 1),
        )

    if scenario_id == "DUPLICATE_IDENTITY":
        return SyntheticBureauReport(
            applicant_synthetic_id=applicant.synthetic_id,
            credit_score=rng.randint(600, 700),
            tradelines=(),
            hard_inquiries_last_12_months=rng.randint(2, 6),
            is_duplicate_identity_flag=True,
        )

    tradeline_count = rng.randint(2, 6)
    tradelines = tuple(
        Tradeline(
            account_type=rng.choice(_ACCOUNT_TYPES),
            opened_years_ago=rng.randint(1, 15),
            balance=rng.randint(0, 15_000),
            credit_limit=rng.randint(1_000, 25_000),
            is_delinquent=rng.random() < 0.05,
        )
        for _ in range(tradeline_count)
    )
    return SyntheticBureauReport(
        applicant_synthetic_id=applicant.synthetic_id,
        credit_score=rng.randint(680, 800),
        tradelines=tradelines,
        hard_inquiries_last_12_months=rng.randint(0, 3),
    )
