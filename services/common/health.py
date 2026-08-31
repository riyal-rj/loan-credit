"""Shared liveness endpoint for mock services -- these are stateless, so liveness is the only
meaningful health signal (there is no downstream dependency for them to be "ready" against)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}
