from __future__ import annotations

from services.synthetic_data.applicants import generate_applicant
from services.synthetic_data.bureau import generate_bureau_report
from services.synthetic_data.employer import generate_employment_record
from services.synthetic_data.kyc import KycStatus, generate_kyc_result
from services.synthetic_data.transactions import generate_transaction_history

_APPLICANT = generate_applicant("NORMAL_ELIGIBLE", 0)


def test_bureau_normal_scenario_has_good_score_and_multiple_tradelines() -> None:
    report = generate_bureau_report(_APPLICANT, "NORMAL_ELIGIBLE")
    assert report.credit_score >= 680
    assert len(report.tradelines) >= 2
    assert not report.is_duplicate_identity_flag


def test_bureau_thin_file_scenario_has_one_tradeline_and_lower_score() -> None:
    report = generate_bureau_report(_APPLICANT, "THIN_FILE_BUREAU")
    assert len(report.tradelines) == 1
    assert report.credit_score < 680


def test_bureau_duplicate_identity_scenario_flags_it() -> None:
    report = generate_bureau_report(_APPLICANT, "DUPLICATE_IDENTITY")
    assert report.is_duplicate_identity_flag


def test_bureau_deterministic_per_applicant_and_scenario() -> None:
    first = generate_bureau_report(_APPLICANT, "NORMAL_ELIGIBLE")
    second = generate_bureau_report(_APPLICANT, "NORMAL_ELIGIBLE")
    assert first == second


def test_kyc_normal_scenario_passes() -> None:
    result = generate_kyc_result(_APPLICANT, "NORMAL_ELIGIBLE")
    assert result.status is KycStatus.PASS
    assert result.date_of_birth_match


def test_kyc_identity_mismatch_scenario_fails() -> None:
    result = generate_kyc_result(_APPLICANT, "KYC_IDENTITY_MISMATCH")
    assert result.status is KycStatus.FAIL
    assert not result.date_of_birth_match


def test_kyc_duplicate_identity_scenario_routes_to_review() -> None:
    result = generate_kyc_result(_APPLICANT, "DUPLICATE_IDENTITY")
    assert result.status is KycStatus.REVIEW


def test_employer_normal_scenario_confirms_close_to_declared_income() -> None:
    record = generate_employment_record(_APPLICANT, "NORMAL_ELIGIBLE")
    assert record.is_employment_confirmed
    assert abs(record.verified_annual_income - _APPLICANT.declared_annual_income) <= (
        _APPLICANT.declared_annual_income * 0.06
    )
    assert record.tenure_months >= 12


def test_employer_mismatch_scenario_reports_materially_lower_income() -> None:
    record = generate_employment_record(_APPLICANT, "EMPLOYER_VERIFICATION_MISMATCH")
    assert record.verified_annual_income < _APPLICANT.declared_annual_income * 0.8
    assert record.tenure_months < 12


def test_transactions_normal_scenario_has_no_nsf_and_healthy_balance() -> None:
    history = generate_transaction_history(_APPLICANT, "NORMAL_ELIGIBLE")
    assert history.nsf_count_last_90_days == 0
    assert history.average_daily_balance > 0
    assert len(history.transactions) > 0


def test_transactions_low_balance_scenario_has_nsf_events() -> None:
    history = generate_transaction_history(_APPLICANT, "LOW_BALANCE_NSF")
    assert history.nsf_count_last_90_days >= 3


def test_transactions_include_periodic_payroll_deposits() -> None:
    history = generate_transaction_history(_APPLICANT, "NORMAL_ELIGIBLE")
    assert any(t.description == "Payroll deposit" for t in history.transactions)
