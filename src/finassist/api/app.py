"""FastAPI application factory -- the API process composition root.

`create_app` is the single place that wires a `Container` into HTTP routes/middleware. Nothing
here is imported by `finassist.domain` or `finassist.application` (enforced by the import-linter
layers contract in `pyproject.toml`), keeping the dependency direction from docs/adr/0001 real.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.responses import Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from finassist.api.error_handling.problem_details import register_error_handlers
from finassist.api.middleware.metrics import MetricsMiddleware
from finassist.api.middleware.request_limits import RequestSizeLimitMiddleware
from finassist.api.routes.health import build_health_router
from finassist.bootstrap.container import Container, build_container, shutdown_container
from finassist.bootstrap.logging import get_logger
from finassist.bootstrap.settings import Settings
from finassist.observability.metrics import REGISTRY

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return a fully-wired FastAPI application.

    The :class:`Container` is built inside the lifespan context (not at import time) so importing
    this module never has side effects -- required for the test suite to import the module safely
    and construct multiple independent apps with different settings.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = build_container(settings)
        app.state.container = container
        app.include_router(build_health_router(container))
        logger.info("api.startup.complete")
        try:
            yield
        finally:
            logger.info("api.shutdown.start")
            await shutdown_container(container)

    app = FastAPI(
        title="FinAssist Underwriting API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    resolved_settings = settings or _settings_for_middleware()
    app.add_middleware(
        RequestSizeLimitMiddleware, max_bytes=resolved_settings.request_body_max_bytes
    )
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    register_error_handlers(app)

    if resolved_settings.otel_enabled:
        FastAPIInstrumentor.instrument_app(app)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    return app


def _settings_for_middleware() -> Settings:
    from finassist.bootstrap.settings import get_settings

    return get_settings()


def get_container(app: FastAPI) -> Container:
    """Retrieve the request-scoped container from application state.

    Use via FastAPI's ``Depends`` in route modules added from Phase 1B onward rather than
    importing a global.
    """
    container: Container = app.state.container
    return container
