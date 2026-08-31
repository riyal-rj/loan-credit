"""Mock loan-origination system (LOS) service.

Represents the *external* system of record this platform augments (master instruction §3: "does
not replace the system of record"). Unlike the other mock services, this one is stateful -- it
holds created cases in memory (reset on restart, which is fine for a demo/test double) so a
created case can later be fetched and have its status updated, simulating our platform writing a
recommendation back to the origination system it doesn't own.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from services.common.health import router as health_router
from services.common.scenario_control import ScenarioDep, apply_fault_behavior

_VALID_STATUSES = frozenset(
    {"RECEIVED", "UNDER_REVIEW", "APPROVED", "DECLINED", "NEEDS_MORE_INFORMATION", "CANCELLED"}
)


class CreateCaseRequest(BaseModel):
    given_name: str = Field(min_length=1)
    family_name: str = Field(min_length=1)
    synthetic_id: str = Field(min_length=1)
    product_code: str = Field(min_length=1)
    requested_amount_cents: int = Field(gt=0)
    requested_term_months: int = Field(gt=0)


class UpdateCaseStatusRequest(BaseModel):
    status: str
    reason: str = Field(min_length=1)


class CaseResponse(BaseModel):
    schema_version: int = 1
    external_case_id: str
    given_name: str
    family_name: str
    synthetic_id: str
    product_code: str
    requested_amount_cents: int
    requested_term_months: int
    status: str
    status_reason: str | None = None
    created_at: datetime
    updated_at: datetime


def create_app() -> FastAPI:
    app = FastAPI(title="Mock Loan Origination System", docs_url="/docs", redoc_url=None)
    app.include_router(health_router)

    cases: dict[str, CaseResponse] = {}
    lock = asyncio.Lock()

    @app.post("/cases", status_code=201)
    async def create_case(payload: CreateCaseRequest, scenario: ScenarioDep) -> CaseResponse:
        if (fault_response := await apply_fault_behavior(scenario)) is not None:
            return fault_response  # type: ignore[return-value]

        now = datetime.now(UTC)
        case = CaseResponse(
            external_case_id=f"LOS-{uuid.uuid4()}",
            given_name=payload.given_name,
            family_name=payload.family_name,
            synthetic_id=payload.synthetic_id,
            product_code=payload.product_code,
            requested_amount_cents=payload.requested_amount_cents,
            requested_term_months=payload.requested_term_months,
            status="RECEIVED",
            created_at=now,
            updated_at=now,
        )
        async with lock:
            cases[case.external_case_id] = case
        return case

    @app.get("/cases/{external_case_id}")
    async def get_case(external_case_id: str, scenario: ScenarioDep) -> CaseResponse:
        if (fault_response := await apply_fault_behavior(scenario)) is not None:
            return fault_response  # type: ignore[return-value]

        async with lock:
            case = cases.get(external_case_id)
        if case is None:
            raise HTTPException(status_code=404, detail=f"case {external_case_id} not found")
        return case

    @app.patch("/cases/{external_case_id}")
    async def update_case_status(
        external_case_id: str, payload: UpdateCaseStatusRequest, scenario: ScenarioDep
    ) -> CaseResponse:
        if (fault_response := await apply_fault_behavior(scenario)) is not None:
            return fault_response  # type: ignore[return-value]

        if payload.status not in _VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {sorted(_VALID_STATUSES)}",
            )

        async with lock:
            case = cases.get(external_case_id)
            if case is None:
                raise HTTPException(status_code=404, detail=f"case {external_case_id} not found")
            updated = case.model_copy(
                update={
                    "status": payload.status,
                    "status_reason": payload.reason,
                    "updated_at": datetime.now(UTC),
                }
            )
            cases[external_case_id] = updated
        return updated

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9105)  # noqa: S104 # nosec B104
