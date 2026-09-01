"""Worker process entrypoint.

Bootstraps the same settings/logging/telemetry stack as the API and, since Phase 3, runs three
background tasks alongside its own liveness endpoint: the Temporal `Worker` (hosts
`ApplicationWorkflow` + its activities), the outbox-relay loop (publishes `integration.
outbox_events` to Kafka), and the projection-consumer loop (maintains `applications.
status_projection` from that same topic). Phase 1A's heartbeat loop is gone -- these three tasks
are the worker's real job now; the process lifecycle/observability/signal-handling scaffolding
around them is unchanged.

Each task is wrapped by `_run_with_retry` (backoff, retry until `stop_event`): compose's
`depends_on: service_healthy` ordering is a best effort, not a guarantee, and a worker that
crash-loops the whole process because Temporal or Kafka took a few extra seconds to become
reachable is exactly the "must not crash-loop on a slow/unavailable dependency" failure
`api/app.py`'s `object_store.ensure_ready()` handling already avoids for the API process.

Run with: ``uv run python -m apps.worker.main`` or ``make run-worker``.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable

import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.bootstrap.container import Container, build_container, shutdown_container
from finassist.bootstrap.logging import get_logger
from finassist.bootstrap.settings import Settings, get_settings
from finassist.infrastructure.kafka.outbox_relay import relay_once
from finassist.infrastructure.kafka.producer import KafkaEventProducer
from finassist.infrastructure.kafka.projection_consumer import run_projection_consumer
from finassist.infrastructure.temporal.worker import build_worker

logger = get_logger(__name__)

_RETRY_BACKOFF_SECONDS = 5.0


def _build_liveness_app() -> FastAPI:
    app = FastAPI(title="FinAssist Worker Liveness", docs_url=None, redoc_url=None)

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "alive"}

    return app


async def _run_with_retry(
    name: str, stop_event: asyncio.Event, run_once: Callable[[], Awaitable[None]]
) -> None:
    """Runs ``run_once()`` repeatedly until it returns normally (the task noticed `stop_event`
    itself and exited cleanly) or `stop_event` is set. An exception -- e.g. Temporal/Kafka not
    reachable yet -- is logged and retried after a fixed backoff rather than propagating."""
    while not stop_event.is_set():
        try:
            await run_once()
        except Exception as exc:  # noqa: BLE001 - see module docstring
            if stop_event.is_set():
                return
            logger.error(f"worker.{name}.failed_will_retry", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_RETRY_BACKOFF_SECONDS)
            except TimeoutError:
                continue
        else:
            return


async def _run_temporal_worker(
    stop_event: asyncio.Event, *, settings: Settings, container: Container
) -> None:
    worker = await build_worker(
        settings=settings,
        uow_factory=container.uow_factory,
        clock=container.clock,
        id_generator=container.id_generator,
        object_store=container.object_store,
        document_parser=container.document_parser,
        document_extractor=container.document_extractor,
        kyc_verifier=container.kyc_verifier,
        employer_verifier=container.employer_verifier,
        bureau_client=container.bureau_client,
        core_banking_client=container.core_banking_client,
    )
    run_task = asyncio.create_task(worker.run())
    await stop_event.wait()
    await worker.shutdown()
    await run_task


async def _run_outbox_relay(
    stop_event: asyncio.Event,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    producer = KafkaEventProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        security_protocol=settings.kafka_security_protocol,
        topic=settings.kafka_applications_topic,
    )
    await producer.ensure_ready()
    try:
        while not stop_event.is_set():
            published = await relay_once(
                session_factory=session_factory,
                producer=producer,
                batch_size=settings.kafka_outbox_relay_batch_size,
            )
            if published:
                logger.info("outbox_relay.published", count=published)
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings.kafka_outbox_relay_poll_interval_seconds,
                )
            except TimeoutError:
                continue
    finally:
        await producer.close()


async def _run_projection_consumer(
    stop_event: asyncio.Event,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await run_projection_consumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        security_protocol=settings.kafka_security_protocol,
        topic=settings.kafka_applications_topic,
        consumer_group=settings.kafka_projection_consumer_group,
        session_factory=session_factory,
        stop_signal=stop_event,
    )


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

    temporal_task = asyncio.create_task(
        _run_with_retry(
            "temporal_worker",
            stop_event,
            lambda: _run_temporal_worker(stop_event, settings=settings, container=container),
        )
    )
    outbox_relay_task = asyncio.create_task(
        _run_with_retry(
            "outbox_relay",
            stop_event,
            lambda: _run_outbox_relay(
                stop_event, session_factory=container.session_factory, settings=settings
            ),
        )
    )
    projection_task = asyncio.create_task(
        _run_with_retry(
            "projection_consumer",
            stop_event,
            lambda: _run_projection_consumer(
                stop_event, session_factory=container.session_factory, settings=settings
            ),
        )
    )
    server_task = asyncio.create_task(server.serve())

    await stop_event.wait()
    logger.info("worker.shutdown.start")
    server.should_exit = True
    await asyncio.gather(
        temporal_task, outbox_relay_task, projection_task, server_task, return_exceptions=True
    )
    await shutdown_container(container)
    logger.info("worker.shutdown.complete")


if __name__ == "__main__":
    asyncio.run(main())
