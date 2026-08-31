from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import load_mock_app

_VALID_REQUEST = {
    "given_name": "Ada",
    "family_name": "Lovelace",
    "synthetic_id": "900-12-3456",
    "declared_annual_income": 80000,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(load_mock_app("mock-core-banking"))


def test_normal_scenario_has_healthy_balance_and_no_nsf(client: TestClient) -> None:
    response = client.post("/transaction-history", json=_VALID_REQUEST)
    assert response.status_code == 200
    body = response.json()
    assert body["average_daily_balance_cents"] > 100_000
    assert body["nsf_count_last_90_days"] == 0
    assert len(body["recent_transactions"]) <= 10


def test_low_balance_nsf_scenario(client: TestClient) -> None:
    response = client.post(
        "/transaction-history",
        json=_VALID_REQUEST,
        headers={"X-Synthetic-Scenario": "LOW_BALANCE_NSF"},
    )
    body = response.json()
    assert body["nsf_count_last_90_days"] >= 3


def test_rate_limited_fault_injection(client: TestClient) -> None:
    response = client.post(
        "/transaction-history",
        json=_VALID_REQUEST,
        headers={"X-Synthetic-Scenario": "CORE_BANKING_RATE_LIMITED"},
    )
    assert response.status_code == 429
