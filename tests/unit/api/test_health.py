from __future__ import annotations

from fastapi.testclient import TestClient

from finassist.api.app import create_app
from finassist.bootstrap.settings import Settings


def _client(**overrides: object) -> TestClient:
    # object_store_request_timeout_seconds is tiny here purely for test speed: no live MinIO in a
    # unit-test run, so every object-store call is expected to fail, and the production default
    # (5s, a reasonable value for a real network call) would make this file slow.
    settings = Settings(
        environment="local",
        log_format="console",
        object_store_request_timeout_seconds=0.1,
        **overrides,  # type: ignore[arg-type]
    )
    app = create_app(settings)
    return TestClient(app)


def test_liveness_returns_alive() -> None:
    with _client() as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_all_registered_checks() -> None:
    # No live Postgres/MinIO in a pure unit-test run, so this only asserts the registry/response
    # shape (every check present, secret_provider healthy since it needs no dependency). The "all
    # healthy, 200" path is covered by tests/integration/test_application_repository.py (Postgres)
    # and tests/integration/test_object_store.py (MinIO) against real containers.
    with _client() as client:
        response = client.get("/health/ready")

    body = response.json()
    assert response.status_code in (200, 503)
    check_names = {check["name"] for check in body["checks"]}
    assert check_names == {"secret_provider", "postgres", "object_store", "workflow_runner"}
    assert any(check["name"] == "secret_provider" and check["healthy"] for check in body["checks"])


def test_metrics_endpoint_exposes_prometheus_format() -> None:
    with _client() as client:
        client.get("/health/live")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "finassist_http_requests_total" in response.text
