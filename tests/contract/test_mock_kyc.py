from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import load_mock_app

_VALID_REQUEST = {
    "given_name": "Ada",
    "family_name": "Lovelace",
    "date_of_birth": "1990-01-01",
    "synthetic_id": "900-12-3456",
    "street_address": "123 Maple St",
    "city": "Springfield",
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(load_mock_app("mock-kyc"))


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_normal_scenario_passes(client: TestClient) -> None:
    response = client.post("/verify", json=_VALID_REQUEST)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["applicant_synthetic_id"] == "900-12-3456"


def test_identity_mismatch_scenario_fails(client: TestClient) -> None:
    response = client.post(
        "/verify",
        json=_VALID_REQUEST,
        headers={"X-Synthetic-Scenario": "KYC_IDENTITY_MISMATCH"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "FAIL"


def test_same_request_and_scenario_is_deterministic(client: TestClient) -> None:
    first = client.post("/verify", json=_VALID_REQUEST).json()
    second = client.post("/verify", json=_VALID_REQUEST).json()
    assert first == second


def test_unknown_scenario_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/verify", json=_VALID_REQUEST, headers={"X-Synthetic-Scenario": "NOT_A_REAL_SCENARIO"}
    )
    assert response.status_code == 400


def test_server_error_fault_injection(client: TestClient) -> None:
    response = client.post(
        "/verify", json=_VALID_REQUEST, headers={"X-Synthetic-Scenario": "KYC_SERVICE_ERROR"}
    )
    assert response.status_code == 500


def test_invalid_request_body_is_rejected(client: TestClient) -> None:
    response = client.post("/verify", json={"given_name": "Ada"})
    assert response.status_code == 422
