from __future__ import annotations

from fastapi.testclient import TestClient

from finassist.api.app import create_app
from finassist.bootstrap.settings import Settings


def _client(**overrides: object) -> TestClient:
    settings = Settings(environment="local", log_format="console", **overrides)  # type: ignore[arg-type]
    app = create_app(settings)
    return TestClient(app)


def test_liveness_returns_alive() -> None:
    with _client() as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_secret_provider_and_postgres_checks() -> None:
    # No live Postgres in a pure unit-test run, so this only asserts the registry/response shape
    # (both checks present, secret_provider healthy). The "all healthy, 200" path is covered by
    # tests/integration/test_health_readiness.py against a real Postgres container.
    with _client() as client:
        response = client.get("/health/ready")

    body = response.json()
    assert response.status_code in (200, 503)
    check_names = {check["name"] for check in body["checks"]}
    assert check_names == {"secret_provider", "postgres"}
    assert any(check["name"] == "secret_provider" and check["healthy"] for check in body["checks"])


def test_metrics_endpoint_exposes_prometheus_format() -> None:
    with _client() as client:
        client.get("/health/live")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "finassist_http_requests_total" in response.text
