"""Mock employer verification service.

See `services/mock-kyc/main.py` for the inline-schema rationale.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field
from services.common.health import router as health_router
from services.common.scenario_control import ScenarioDep, apply_fault_behavior
from services.synthetic_data.applicants import SyntheticApplicant
from services.synthetic_data.employer import generate_employment_record


class VerifyEmploymentRequest(BaseModel):
    given_name: str = Field(min_length=1)
    family_name: str = Field(min_length=1)
    synthetic_id: str = Field(min_length=1)
    employer_name: str = Field(min_length=1)
    declared_annual_income: int = Field(gt=0)


class VerifyEmploymentResponse(BaseModel):
    schema_version: int = 1
    applicant_synthetic_id: str
    employer_name: str
    is_employment_confirmed: bool
    verified_annual_income: int
    tenure_months: int


def create_app() -> FastAPI:
    app = FastAPI(title="Mock Employer Verification Service", docs_url="/docs", redoc_url=None)
    app.include_router(health_router)

    @app.post("/verify-employment")
    async def verify_employment(
        payload: VerifyEmploymentRequest, scenario: ScenarioDep
    ) -> VerifyEmploymentResponse:
        if (fault_response := await apply_fault_behavior(scenario)) is not None:
            return fault_response  # type: ignore[return-value]

        applicant = SyntheticApplicant(
            synthetic_id=payload.synthetic_id,
            given_name=payload.given_name,
            family_name=payload.family_name,
            date_of_birth=date(1990, 1, 1),
            email="",
            street_address="",
            city="",
            employer_name=payload.employer_name,
            declared_annual_income=payload.declared_annual_income,
        )
        record = generate_employment_record(applicant, scenario.scenario_id)
        return VerifyEmploymentResponse(
            applicant_synthetic_id=record.applicant_synthetic_id,
            employer_name=record.employer_name,
            is_employment_confirmed=record.is_employment_confirmed,
            verified_annual_income=record.verified_annual_income,
            tenure_months=record.tenure_months,
        )

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9103)  # noqa: S104 # nosec B104
