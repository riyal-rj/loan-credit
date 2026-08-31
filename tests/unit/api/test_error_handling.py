from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finassist.api.app import create_app
from finassist.api.error_handling.problem_details import PROBLEM_CONTENT_TYPE, DomainError
from finassist.bootstrap.settings import Settings


class _ExampleNotFoundError(DomainError):
    http_status = 404
    problem_type = "https://finassist.example/problems/example-not-found"
    code = "example_not_found"


def _app_with_test_route() -> FastAPI:
    settings = Settings(
        environment="local", log_format="console", object_store_request_timeout_seconds=0.1
    )
    app = create_app(settings)

    @app.get("/__test/domain-error")
    async def _raise_domain_error() -> None:
        raise _ExampleNotFoundError("the example was not found")

    @app.get("/__test/unexpected-error")
    async def _raise_unexpected_error() -> None:
        raise RuntimeError("boom")

    return app


def test_domain_error_is_mapped_to_problem_details() -> None:
    app = _app_with_test_route()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__test/domain-error")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = response.json()
    assert body["code"] == "example_not_found"
    assert body["status"] == 404
    assert "the example was not found" in body["detail"]


def test_unexpected_error_never_leaks_internal_message() -> None:
    app = _app_with_test_route()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__test/unexpected-error")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_server_error"
    assert "boom" not in body["detail"]


def test_validation_error_returns_field_level_detail() -> None:
    settings = Settings(
        environment="local", log_format="console", object_store_request_timeout_seconds=0.1
    )
    app = create_app(settings)

    @app.get("/__test/validated")
    async def _validated(count: int) -> dict[str, int]:
        return {"count": count}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__test/validated", params={"count": "not-an-int"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "request_validation_failed"
    assert body["errors"]


def test_oversized_request_body_is_rejected() -> None:
    settings = Settings(
        environment="local",
        log_format="console",
        request_body_max_bytes=1024,
        object_store_request_timeout_seconds=0.1,
    )
    app = create_app(settings)

    @app.post("/__test/upload")
    async def _upload() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/__test/upload", content=b"x" * 2000)

    assert response.status_code == 413
