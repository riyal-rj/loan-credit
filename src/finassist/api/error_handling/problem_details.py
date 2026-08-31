"""RFC 9457 ("Problem Details for HTTP APIs") error mapping.

Domain/application exceptions never leak a raw traceback or internal message to a client. Every
unhandled path is mapped here to a `ProblemDetail` response with a stable `type`/`code`, so API
consumers can branch on `code` rather than parsing prose, per master instruction §11.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from finassist.bootstrap.logging import get_logger
from finassist.domain.applications.exceptions import (
    ApplicationNotFoundError,
    ConcurrencyConflictError,
    DuplicateRequestError,
    IllegalStateTransitionError,
    InvalidApplicationDataError,
    NoActiveWorkflowError,
    ProductNotFoundError,
    ProductRejectedRequestError,
)

logger = get_logger(__name__)

# Domain/application exceptions never subclass `DomainError` -- doing so would require
# `finassist.domain` to import `finassist.api`, which the import-linter layers contract forbids.
# This table is the API layer's mapping from a plain domain exception type to the RFC 9457
# response it becomes, kept in one place instead of scattered per-route try/except blocks
# (master instruction §11: "meaningful problem codes for policy, authorization, validation, and
# dependency failures").
_DOMAIN_EXCEPTION_STATUS: dict[type[Exception], tuple[int, str]] = {
    ApplicationNotFoundError: (status.HTTP_404_NOT_FOUND, "application_not_found"),
    ProductNotFoundError: (status.HTTP_404_NOT_FOUND, "product_not_found"),
    DuplicateRequestError: (status.HTTP_409_CONFLICT, "duplicate_request"),
    ConcurrencyConflictError: (status.HTTP_409_CONFLICT, "concurrency_conflict"),
    IllegalStateTransitionError: (status.HTTP_409_CONFLICT, "illegal_state_transition"),
    NoActiveWorkflowError: (status.HTTP_409_CONFLICT, "no_active_workflow"),
    ProductRejectedRequestError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "product_rejected_request",
    ),
    InvalidApplicationDataError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_application_data",
    ),
}

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ProblemDetail(BaseModel):
    """RFC 9457 problem-details body."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    correlation_id: str | None = None
    errors: list[dict[str, Any]] | None = None


class DomainError(Exception):
    """Base class for exceptions the API layer knows how to map to a `ProblemDetail`.

    Application/domain code raises subclasses of this (or registers a mapping via
    `register_problem_mapping`) instead of raising bare `Exception`/`ValueError` across the API
    boundary, so every consequential failure has a stable machine-readable `code`.
    """

    http_status: int = status.HTTP_400_BAD_REQUEST
    problem_type: str = "about:blank"
    code: str = "domain_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None) or request.headers.get("X-Request-ID")


def _problem_response(
    request: Request,
    *,
    http_status: int,
    title: str,
    detail: str,
    code: str,
    problem_type: str = "about:blank",
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        type=problem_type,
        title=title,
        status=http_status,
        detail=detail,
        code=code,
        correlation_id=_correlation_id(request),
        errors=errors,
    )
    return JSONResponse(
        status_code=http_status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register the RFC 9457 exception handlers on ``app``. Call once from the app factory."""

    @app.exception_handler(DomainError)
    async def _handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        logger.warning("api.domain_error", code=exc.code, detail=exc.detail)
        return _problem_response(
            request,
            http_status=exc.http_status,
            title=exc.__class__.__name__,
            detail=exc.detail,
            code=exc.code,
            problem_type=exc.problem_type,
        )

    for exc_type, (http_status, code) in _DOMAIN_EXCEPTION_STATUS.items():

        def _make_handler(
            http_status: int, code: str
        ) -> Any:
            async def _handle(request: Request, exc: Exception) -> JSONResponse:
                logger.warning("api.domain_error", code=code, detail=str(exc))
                return _problem_response(
                    request,
                    http_status=http_status,
                    title=type(exc).__name__,
                    detail=str(exc),
                    code=code,
                )

            return _handle

        app.add_exception_handler(exc_type, _make_handler(http_status, code))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.info("api.validation_error", error_count=len(exc.errors()))
        return _problem_response(
            request,
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Request Validation Failed",
            detail="One or more request fields failed validation.",
            code="request_validation_failed",
            errors=[
                {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
                for err in exc.errors()
            ],
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("api.unhandled_exception", exc_info=exc, error_class=type(exc).__name__)
        return _problem_response(
            request,
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal Server Error",
            detail="An unexpected error occurred. This has been logged for investigation.",
            code="internal_server_error",
        )
