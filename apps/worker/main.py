"""Worker process entrypoint (Phase 1A boot path only).

This process bootstraps the same settings/logging/telemetry stack as the API and runs a heartbeat
loop plus its own liveness endpoint, so it is independently deployable, observable, and
probe-able from the first commit. It deliberately does **not** connect to Temporal yet -- durable
workflow/activity execution is Phase 3 scope (docs/architecture/phase-0-assessment.md §5). Adding
Temporal here will replace the heartbeat loop's body, not the process's lifecycle/observability
scaffolding.

Run with: ``uv run python -m apps.worker.main`` or ``make run-worker``.
"""

from __future__ import annotations

import asyncio
import signal

import uvicorn
from fastapi import FastAPI

from finassist.bootstrap.container import build_container, shutdown_container
from finassist.bootstrap.logging import get_logger
from finassist.bootstrap.settings import get_settings

logger = get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30.0


def _build_liveness_app() -> FastAPI:
    app = FastAPI(title="FinAssist Worker Liveness", docs_url=None, redoc_url=None)

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "alive"}

    return app


async def _heartbeat_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        logger.info("worker.heartbeat")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
        except TimeoutError:
            continue


async def main() -> None:
    settings = get_settings()
    container = build_container(settings)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # ProactorEventLoop (default on Windows) does not support add_signal_handler.
            # Fall back to the synchronous signal API, which still works for Ctrl+C/terminate.
            signal.signal(sig, lambda *_args: loop.call_soon_threadsafe(stop_event.set))

    liveness_app = _build_liveness_app()
    uvicorn_config = uvicorn.Config(
        liveness_app,
        host=settings.http_host,
        port=settings.http_port,
        log_config=None,
    )
    server = uvicorn.Server(uvicorn_config)

    logger.info("worker.startup.complete", liveness_port=settings.http_port)

    heartbeat_task = asyncio.create_task(_heartbeat_loop(stop_event))
    server_task = asyncio.create_task(server.serve())

    await stop_event.wait()
    logger.info("worker.shutdown.start")
    server.should_exit = True
    await asyncio.gather(heartbeat_task, server_task, return_exceptions=True)
    await shutdown_container(container)
    logger.info("worker.shutdown.complete")


if __name__ == "__main__":
    asyncio.run(main())
