"""A complete synthetic case: applicant plus every downstream record, generated consistently
for one `(scenario_id, index)` pair. Used by demo/evaluation seeding and by tests that need a
whole plausible case rather than one record type at a time.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.synthetic_data.applicants import SyntheticApplicant, generate_applicant
from services.synthetic_data.bureau import SyntheticBureauReport, generate_bureau_report
from services.synthetic_data.employer import SyntheticEmploymentRecord, generate_employment_record
from services.synthetic_data.kyc import SyntheticKycResult, generate_kyc_result
from services.synthetic_data.transactions import (
    SyntheticTransactionHistory,
    generate_transaction_history,
)


@dataclass(frozen=True, slots=True)
class SyntheticCaseBundle:
    scenario_id: str
    applicant: SyntheticApplicant
    bureau_report: SyntheticBureauReport
    kyc_result: SyntheticKycResult
    employment: SyntheticEmploymentRecord
    transaction_history: SyntheticTransactionHistory


def generate_case_bundle(scenario_id: str, index: int = 0) -> SyntheticCaseBundle:
    applicant = generate_applicant(scenario_id, index)
    return SyntheticCaseBundle(
        scenario_id=scenario_id,
        applicant=applicant,
        bureau_report=generate_bureau_report(applicant, scenario_id, index),
        kyc_result=generate_kyc_result(applicant, scenario_id, index),
        employment=generate_employment_record(applicant, scenario_id, index),
        transaction_history=generate_transaction_history(applicant, scenario_id, index),
    )
