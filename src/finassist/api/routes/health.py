"""Liveness/readiness endpoints.

Readiness is implemented as an extensible registry of async dependency checks (`ReadinessCheck`)
rather than a hard-coded `True`, so Phase 1B+ can register a PostgreSQL/Valkey/Qdrant/Kafka check
by appending to the registry without changing this module or its response contract. In Phase 1A
the only checks are the ones that are actually meaningful yet: settings loaded successfully and
the configured secret provider is constructible/reachable.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from finassist.bootstrap.container import Container
from finassist.bootstrap.logging import get_logger
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
    # There is no required secret to resolve yet in Phase 1A; constructing the provider at
    # container build time already proved it is wired correctly. This check exists so the
    # registry pattern -- and the failure-reporting path below -- is exercised end-to-end before
    # Phase 1B adds checks with real failure modes (a database that can be down).
    if container.secret_provider is None:  # pragma: no cover - defensive, container guarantees this
        raise RuntimeError("secret provider not initialized")


READINESS_CHECKS: list[ReadinessCheck] = [
    ReadinessCheck(name="secret_provider", check=_check_secret_provider),
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
