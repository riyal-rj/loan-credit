"""ASGI middleware recording the Phase 1A HTTP metrics from `finassist.observability.metrics`."""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from finassist.observability.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_FLIGHT,
    HTTP_REQUESTS_TOTAL,
)


class MetricsMiddleware:
    """Records request count, duration, and in-flight gauge with low-cardinality labels.

    The route label uses the matched route path template (e.g. ``/api/v1/applications/{id}``),
    never the raw request path, so path parameters never inflate metric cardinality.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        HTTP_REQUESTS_IN_FLIGHT.inc()
        start = time.perf_counter()
        status_code_holder: dict[str, int] = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code_holder["code"] = _coerce_status_code(message.get("status"))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            route = _route_template(request)
            HTTP_REQUESTS_IN_FLIGHT.dec()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, route=route).observe(
                duration
            )
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method,
                route=route,
                status_code=str(status_code_holder["code"]),
            ).inc()


def _coerce_status_code(raw_status: Any) -> int:
    if isinstance(raw_status, int):
        return raw_status
    return 500


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path_template = getattr(route, "path", None)
    if isinstance(path_template, str):
        return path_template
    return "unmatched"
