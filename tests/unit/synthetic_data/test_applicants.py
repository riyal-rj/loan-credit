from __future__ import annotations

from services.synthetic_data.applicants import generate_applicant


def test_deterministic_for_same_scenario_and_index() -> None:
    a = generate_applicant("NORMAL_ELIGIBLE", 0)
    b = generate_applicant("NORMAL_ELIGIBLE", 0)
    assert a == b


def test_different_index_produces_different_identity() -> None:
    a = generate_applicant("NORMAL_ELIGIBLE", 0)
    b = generate_applicant("NORMAL_ELIGIBLE", 1)
    assert a.synthetic_id != b.synthetic_id


def test_synthetic_id_is_not_a_valid_real_ssn_range() -> None:
    applicant = generate_applicant("NORMAL_ELIGIBLE", 0)
    assert applicant.synthetic_id.startswith("900-")


def test_email_is_synthetic_domain() -> None:
    applicant = generate_applicant("NORMAL_ELIGIBLE", 0)
    assert applicant.email.endswith("@synthetic.test")
