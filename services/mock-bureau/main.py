"""Mock credit bureau service. See `services/mock-kyc/main.py` for why schemas live inline here."""

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
from services.synthetic_data.bureau import generate_bureau_report


class CreditReportRequest(BaseModel):
    given_name: str = Field(min_length=1)
    family_name: str = Field(min_length=1)
    date_of_birth: date
    synthetic_id: str = Field(min_length=1)


class TradelineResponse(BaseModel):
    account_type: str
    opened_years_ago: int
    balance: int
    credit_limit: int
    is_delinquent: bool


class CreditReportResponse(BaseModel):
    schema_version: int = 1
    applicant_synthetic_id: str
    credit_score: int
    tradelines: list[TradelineResponse]
    hard_inquiries_last_12_months: int
    is_duplicate_identity_flag: bool


def create_app() -> FastAPI:
    app = FastAPI(title="Mock Credit Bureau Service", docs_url="/docs", redoc_url=None)
    app.include_router(health_router)

    @app.post("/credit-report")
    async def credit_report(
        payload: CreditReportRequest, scenario: ScenarioDep
    ) -> CreditReportResponse:
        if (fault_response := await apply_fault_behavior(scenario)) is not None:
            return fault_response  # type: ignore[return-value]

        applicant = SyntheticApplicant(
            synthetic_id=payload.synthetic_id,
            given_name=payload.given_name,
            family_name=payload.family_name,
            date_of_birth=payload.date_of_birth,
            email="",
            street_address="",
            city="",
            employer_name="",
            declared_annual_income=0,
        )
        report = generate_bureau_report(applicant, scenario.scenario_id)
        return CreditReportResponse(
            applicant_synthetic_id=report.applicant_synthetic_id,
            credit_score=report.credit_score,
            tradelines=[
                TradelineResponse(
                    account_type=t.account_type,
                    opened_years_ago=t.opened_years_ago,
                    balance=t.balance,
                    credit_limit=t.credit_limit,
                    is_delinquent=t.is_delinquent,
                )
                for t in report.tradelines
            ],
            hard_inquiries_last_12_months=report.hard_inquiries_last_12_months,
            is_duplicate_identity_flag=report.is_duplicate_identity_flag,
        )

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9102)  # noqa: S104 # nosec B104
