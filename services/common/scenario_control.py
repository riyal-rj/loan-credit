"""FastAPI plumbing shared by every mock service: resolve the requested scenario from a header,
then apply whatever fault behavior (if any) that scenario specifies.

Callers request a scenario via the `X-Synthetic-Scenario` header (never a body field -- keeps a
mock's request schema looking like the real domain payload it stands in for, per the mock's own
`schemas.py`). Omitting the header defaults to `NORMAL_ELIGIBLE`.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Response
from services.synthetic_data.scenarios import (
    FaultBehavior,
    Scenario,
    UnknownScenarioError,
    get_scenario,
)

SCENARIO_HEADER_NAME = "X-Synthetic-Scenario"
DEFAULT_FAULT_TIMEOUT_SECONDS = 2.0


async def _resolve_scenario_header(
    x_synthetic_scenario: Annotated[str | None, Header(alias=SCENARIO_HEADER_NAME)] = None,
) -> Scenario:
    try:
        return get_scenario(x_synthetic_scenario)
    except UnknownScenarioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


ScenarioDep = Annotated[Scenario, Depends(_resolve_scenario_header)]


async def apply_fault_behavior(
    scenario: Scenario, *, timeout_seconds: float = DEFAULT_FAULT_TIMEOUT_SECONDS
) -> Response | None:
    """Apply `scenario.fault`.

    Returns a `Response` the caller must return immediately (only for `MALFORMED_RESPONSE`), or
    `None` if the caller should proceed to build its normal response. Raises `HTTPException` for
    `SERVER_ERROR`/`RATE_LIMITED`. Sleeps for `TIMEOUT` and then returns `None` (simulating a
    slow-but-eventually-responding upstream, which is what most client-side timeout/retry logic
    needs to exercise -- the caller's own timeout is what should fire in a real chaos test).
    """
    match scenario.fault:
        case FaultBehavior.NONE:
            return None
        case FaultBehavior.TIMEOUT:
            await asyncio.sleep(timeout_seconds)
            return None
        case FaultBehavior.SERVER_ERROR:
            raise HTTPException(
                status_code=500, detail=f"synthetic fault injected: {scenario.scenario_id}"
            )
        case FaultBehavior.RATE_LIMITED:
            raise HTTPException(
                status_code=429, detail=f"synthetic fault injected: {scenario.scenario_id}"
            )
        case FaultBehavior.MALFORMED_RESPONSE:
            return Response(
                content=b'{"malformed": tru',
                media_type="application/json",
                status_code=200,
            )
    raise AssertionError(f"unhandled fault behavior: {scenario.fault}")  # pragma: no cover
