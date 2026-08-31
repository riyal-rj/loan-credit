"""Liveness/readiness endpoints.

Readiness is implemented as an extensible registry of async dependency checks (`ReadinessCheck`)
rather than a hard-coded `True`, so a later phase can register a Valkey/Qdrant/Kafka check by
appending to the registry without changing this module or its response contract. Phase 1B added
the first real dependency check (PostgreSQL connectivity) alongside Phase 1A's secret-provider
check.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from finassist.bootstrap.container import Container
from finassist.bootstrap.logging import get_logger
from finassist.infrastructure.postgres.database import check_connectivity
from finassist.observability.metrics import READINESS_CHECK_FAILURES_TOTAL

logger = get_logger(__name__)

router = APIRouter(tags=["health"])

ReadinessCheckFn = Callable[[Container], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    """A named, independently-failing readiness dependency check.

    ``check`` must raise on failure (any exception) and return normally on success. It must not
    mutate shared state and must complete quickly -- readiness checks run on every probe interval.
    """

    name: str
    check: ReadinessCheckFn


async def _check_secret_provider(container: Container) -> None:
    # There is no required secret to resolve yet; constructing the provider at container build
    # time already proved it is wired correctly. This check exists so the registry pattern -- and
    # the failure-reporting path below -- has at least one dependency-free example alongside the
    # real ones below.
    if container.secret_provider is None:  # pragma: no cover - defensive, container guarantees this
        raise RuntimeError("secret provider not initialized")


async def _check_postgres(container: Container) -> None:
    await check_connectivity(container.engine)


async def _check_object_store(container: Container) -> None:
    await container.object_store.check_connectivity()


READINESS_CHECKS: list[ReadinessCheck] = [
    ReadinessCheck(name="secret_provider", check=_check_secret_provider),
    ReadinessCheck(name="postgres", check=_check_postgres),
    ReadinessCheck(name="object_store", check=_check_object_store),
]


class LivenessResponse(BaseModel):
    status: str = "alive"


class ReadinessCheckResult(BaseModel):
    name: str
    healthy: bool
    error: str | None = None
    duration_ms: float


class ReadinessResponse(BaseModel):
    status: str
    checks: list[ReadinessCheckResult]


def build_health_router(container: Container) -> APIRouter:
    """Bind the health router to a specific :class:`Container` instance.

    Called once from the app factory (composition root) so the router closes over the real,
    already-built container rather than reaching into a global.
    """

    @router.get("/health/live", response_model=LivenessResponse)
    async def liveness() -> LivenessResponse:
        return LivenessResponse()

    @router.get("/health/ready", response_model=ReadinessResponse)
    async def readiness(response: Response) -> ReadinessResponse:
        results: list[ReadinessCheckResult] = []
        all_healthy = True
        for readiness_check in READINESS_CHECKS:
            start = time.perf_counter()
            try:
                await readiness_check.check(container)
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any check failure means "not ready"
                duration_ms = (time.perf_counter() - start) * 1000
                results.append(
                    ReadinessCheckResult(
                        name=readiness_check.name,
                        healthy=False,
                        error=str(exc),
                        duration_ms=duration_ms,
                    )
                )
                READINESS_CHECK_FAILURES_TOTAL.labels(dependency=readiness_check.name).inc()
                all_healthy = False
                logger.warning(
                    "health.readiness_check_failed",
                    dependency=readiness_check.name,
                    error=str(exc),
                )
            else:
                duration_ms = (time.perf_counter() - start) * 1000
                results.append(
                    ReadinessCheckResult(
                        name=readiness_check.name, healthy=True, duration_ms=duration_ms
                    )
                )

        response.status_code = (
            status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return ReadinessResponse(status="ready" if all_healthy else "not_ready", checks=results)

    return router
