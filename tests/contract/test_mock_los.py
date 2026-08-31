from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import load_mock_app

_CREATE_REQUEST = {
    "given_name": "Ada",
    "family_name": "Lovelace",
    "synthetic_id": "900-12-3456",
    "product_code": "PERSONAL_LOAN_USD",
    "requested_amount_cents": 500_000,
    "requested_term_months": 24,
}


@pytest.fixture
def client() -> TestClient:
    # Function-scoped (not module-scoped like the other mock services): mock-los is stateful,
    # and tests must not see cases created by earlier tests.
    return TestClient(load_mock_app("mock-los"))


def test_create_then_get_case(client: TestClient) -> None:
    create_response = client.post("/cases", json=_CREATE_REQUEST)
    assert create_response.status_code == 201
    case = create_response.json()
    assert case["status"] == "RECEIVED"

    get_response = client.get(f"/cases/{case['external_case_id']}")
    assert get_response.status_code == 200
    assert get_response.json() == case


def test_get_unknown_case_returns_404(client: TestClient) -> None:
    response = client.get("/cases/LOS-does-not-exist")
    assert response.status_code == 404


def test_update_case_status(client: TestClient) -> None:
    case = client.post("/cases", json=_CREATE_REQUEST).json()

    update_response = client.patch(
        f"/cases/{case['external_case_id']}",
        json={"status": "APPROVED", "reason": "synthetic approval for testing"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "APPROVED"
    assert updated["status_reason"] == "synthetic approval for testing"
    assert updated["updated_at"] >= case["updated_at"]


def test_update_with_invalid_status_is_rejected(client: TestClient) -> None:
    case = client.post("/cases", json=_CREATE_REQUEST).json()

    response = client.patch(
        f"/cases/{case['external_case_id']}",
        json={"status": "NOT_A_REAL_STATUS", "reason": "x"},
    )
    assert response.status_code == 422


def test_update_unknown_case_returns_404(client: TestClient) -> None:
    response = client.patch("/cases/LOS-does-not-exist", json={"status": "APPROVED", "reason": "x"})
    assert response.status_code == 404
