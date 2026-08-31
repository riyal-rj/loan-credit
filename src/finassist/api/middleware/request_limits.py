"""Request-size limiting middleware.

A minimal, always-on input-validation control (master instruction §18: "strict input validation
... request-size limits") applied before any route/body parsing happens, so an oversized payload
never reaches application code.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from finassist.api.error_handling.problem_details import PROBLEM_CONTENT_TYPE


class RequestSizeLimitMiddleware:
    """Rejects requests whose declared ``Content-Length`` exceeds ``max_bytes``."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        headers = dict(raw_headers)
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > self.max_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "type": "about:blank",
                        "title": "Payload Too Large",
                        "status": 413,
                        "detail": f"Request body exceeds the {self.max_bytes}-byte limit.",
                        "code": "request_body_too_large",
                    },
                    media_type=PROBLEM_CONTENT_TYPE,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
