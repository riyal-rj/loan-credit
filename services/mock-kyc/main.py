"""Mock KYC (identity verification) service.

Standalone FastAPI app -- run directly (``python main.py``) or via uvicorn with ``--app-dir``.
Schemas are defined in this file rather than a sibling module because this directory's name
(``mock-kyc``) is not a valid Python identifier and can't be dotted-imported; keeping each mock
service self-contained avoids fragile `sys.path`/module-name games (see
``tests/contract/conftest.py`` for how tests load this file without executing it as `__main__`).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Allow `from services.synthetic_data...` / `from services.common...` regardless of cwd when this
# file is executed directly (`python services/mock-kyc/main.py`) rather than imported.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field
from services.common.health import router as health_router
from services.common.scenario_control import ScenarioDep, apply_fault_behavior
from services.synthetic_data.applicants import SyntheticApplicant
from services.synthetic_data.kyc import generate_kyc_result


class VerifyIdentityRequest(BaseModel):
    given_name: str = Field(min_length=1)
    family_name: str = Field(min_length=1)
    date_of_birth: date
    synthetic_id: str = Field(min_length=1)
    street_address: str = Field(min_length=1)
    city: str = Field(min_length=1)


class VerifyIdentityResponse(BaseModel):
    schema_version: int = 1
    applicant_synthetic_id: str
    status: str
    name_match_score: float
    address_match_score: float
    date_of_birth_match: bool
    reference_id: str


def create_app() -> FastAPI:
    app = FastAPI(title="Mock KYC Service", docs_url="/docs", redoc_url=None)
    app.include_router(health_router)

    @app.post("/verify")
    async def verify(
        payload: VerifyIdentityRequest, scenario: ScenarioDep
    ) -> VerifyIdentityResponse:
        if (fault_response := await apply_fault_behavior(scenario)) is not None:
            return fault_response  # type: ignore[return-value]

        applicant = SyntheticApplicant(
            synthetic_id=payload.synthetic_id,
            given_name=payload.given_name,
            family_name=payload.family_name,
            date_of_birth=payload.date_of_birth,
            email="",
            street_address=payload.street_address,
            city=payload.city,
            employer_name="",
            declared_annual_income=0,
        )
        result = generate_kyc_result(applicant, scenario.scenario_id)
        return VerifyIdentityResponse(
            applicant_synthetic_id=result.applicant_synthetic_id,
            status=result.status.value,
            name_match_score=result.name_match_score,
            address_match_score=result.address_match_score,
            date_of_birth_match=result.date_of_birth_match,
            reference_id=result.reference_id,
        )

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9101)  # noqa: S104 # nosec B104
