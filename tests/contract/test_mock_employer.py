from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import load_mock_app

_VALID_REQUEST = {
    "given_name": "Ada",
    "family_name": "Lovelace",
    "synthetic_id": "900-12-3456",
    "employer_name": "Northwind Traders Inc.",
    "declared_annual_income": 80000,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(load_mock_app("mock-employer"))


def test_normal_scenario_confirms_declared_income_closely(client: TestClient) -> None:
    response = client.post("/verify-employment", json=_VALID_REQUEST)
    assert response.status_code == 200
    body = response.json()
    assert body["is_employment_confirmed"] is True
    assert 0.9 * 80000 <= body["verified_annual_income"] <= 1.1 * 80000
    assert body["tenure_months"] >= 12


def test_mismatch_scenario_reports_lower_income_and_short_tenure(client: TestClient) -> None:
    response = client.post(
        "/verify-employment",
        json=_VALID_REQUEST,
        headers={"X-Synthetic-Scenario": "EMPLOYER_VERIFICATION_MISMATCH"},
    )
    body = response.json()
    assert body["verified_annual_income"] < 80000 * 0.8
    assert body["tenure_months"] < 12


def test_malformed_response_fault_injection(client: TestClient) -> None:
    response = client.post(
        "/verify-employment",
        json=_VALID_REQUEST,
        headers={"X-Synthetic-Scenario": "EMPLOYER_SERVICE_MALFORMED"},
    )
    assert response.status_code == 200
    with pytest.raises(ValueError):
        response.json()


def test_invalid_income_is_rejected(client: TestClient) -> None:
    bad_request = {**_VALID_REQUEST, "declared_annual_income": -1}
    response = client.post("/verify-employment", json=bad_request)
    assert response.status_code == 422
