from __future__ import annotations

from services.synthetic_data.case_bundle import generate_case_bundle


def test_bundle_is_internally_consistent() -> None:
    bundle = generate_case_bundle("NORMAL_ELIGIBLE", 0)
    assert bundle.bureau_report.applicant_synthetic_id == bundle.applicant.synthetic_id
    assert bundle.kyc_result.applicant_synthetic_id == bundle.applicant.synthetic_id
    assert bundle.employment.applicant_synthetic_id == bundle.applicant.synthetic_id
    assert bundle.transaction_history.applicant_synthetic_id == bundle.applicant.synthetic_id


def test_bundle_is_deterministic() -> None:
    first = generate_case_bundle("THIN_FILE_BUREAU", 3)
    second = generate_case_bundle("THIN_FILE_BUREAU", 3)
    assert first == second


def test_bundle_reflects_requested_scenario_in_every_sub_record() -> None:
    bundle = generate_case_bundle("KYC_IDENTITY_MISMATCH", 0)
    assert bundle.kyc_result.status.value == "FAIL"
