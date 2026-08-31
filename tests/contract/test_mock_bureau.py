from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import load_mock_app

_VALID_REQUEST = {
    "given_name": "Ada",
    "family_name": "Lovelace",
    "date_of_birth": "1990-01-01",
    "synthetic_id": "900-12-3456",
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(load_mock_app("mock-bureau"))


def test_normal_scenario_returns_good_score_with_tradelines(client: TestClient) -> None:
    response = client.post("/credit-report", json=_VALID_REQUEST)
    assert response.status_code == 200
    body = response.json()
    assert body["credit_score"] >= 680
    assert len(body["tradelines"]) >= 2
    assert body["is_duplicate_identity_flag"] is False


def test_thin_file_scenario_returns_minimal_history(client: TestClient) -> None:
    response = client.post(
        "/credit-report", json=_VALID_REQUEST, headers={"X-Synthetic-Scenario": "THIN_FILE_BUREAU"}
    )
    body = response.json()
    assert len(body["tradelines"]) == 1
    assert body["credit_score"] < 680


def test_duplicate_identity_scenario_flags_it(client: TestClient) -> None:
    response = client.post(
        "/credit-report",
        json=_VALID_REQUEST,
        headers={"X-Synthetic-Scenario": "DUPLICATE_IDENTITY"},
    )
    assert response.json()["is_duplicate_identity_flag"] is True


def test_timeout_fault_injection_delays_but_still_responds(client: TestClient) -> None:
    import time

    start = time.perf_counter()
    response = client.post(
        "/credit-report",
        json=_VALID_REQUEST,
        headers={"X-Synthetic-Scenario": "BUREAU_SERVICE_TIMEOUT"},
    )
    elapsed = time.perf_counter() - start
    assert response.status_code == 200
    assert elapsed >= 1.5


def test_deterministic_per_applicant_and_scenario(client: TestClient) -> None:
    first = client.post("/credit-report", json=_VALID_REQUEST).json()
    second = client.post("/credit-report", json=_VALID_REQUEST).json()
    assert first == second
