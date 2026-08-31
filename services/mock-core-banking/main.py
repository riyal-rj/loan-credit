"""Mock core-banking (transaction history) service. See `services/mock-kyc/main.py` for the
inline-schema rationale."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field
from services.common.health import router as health_router
from services.common.scenario_control import ScenarioDep, apply_fault_behavior
from services.synthetic_data.applicants import SyntheticApplicant
from services.synthetic_data.transactions import generate_transaction_history

_RECENT_TRANSACTION_LIMIT = 10


class TransactionHistoryRequest(BaseModel):
    given_name: str = Field(min_length=1)
    family_name: str = Field(min_length=1)
    synthetic_id: str = Field(min_length=1)
    declared_annual_income: int = Field(gt=0)


class TransactionResponse(BaseModel):
    occurred_at: datetime
    amount_cents: int
    description: str


class TransactionHistoryResponse(BaseModel):
    schema_version: int = 1
    applicant_synthetic_id: str
    average_daily_balance_cents: int
    nsf_count_last_90_days: int
    recent_transactions: list[TransactionResponse]


def create_app() -> FastAPI:
    app = FastAPI(title="Mock Core Banking Service", docs_url="/docs", redoc_url=None)
    app.include_router(health_router)

    @app.post("/transaction-history")
    async def transaction_history(
        payload: TransactionHistoryRequest, scenario: ScenarioDep
    ) -> TransactionHistoryResponse:
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
            employer_name="",
            declared_annual_income=payload.declared_annual_income,
        )
        history = generate_transaction_history(applicant, scenario.scenario_id)
        recent = history.transactions[-_RECENT_TRANSACTION_LIMIT:]
        return TransactionHistoryResponse(
            applicant_synthetic_id=history.applicant_synthetic_id,
            average_daily_balance_cents=history.average_daily_balance,
            nsf_count_last_90_days=history.nsf_count_last_90_days,
            recent_transactions=[
                TransactionResponse(
                    occurred_at=t.occurred_at, amount_cents=t.amount, description=t.description
                )
                for t in recent
            ],
        )

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9104)  # noqa: S104 # nosec B104
