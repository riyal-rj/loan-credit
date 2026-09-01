"""`HttpCoreBankingClient`: the `CoreBankingClient` port's adapter for `services/mock-core-banking`
(Phase 2)."""

from __future__ import annotations

from datetime import datetime

import httpx

from finassist.application.ports.external_verification import (
    CoreBankingClient,
    Transaction,
    TransactionHistory,
)


class HttpCoreBankingClient(CoreBankingClient):
    def __init__(self, *, base_url: str, request_timeout_seconds: float) -> None:
        self._base_url = base_url
        self._timeout = httpx.Timeout(request_timeout_seconds)

    async def check_connectivity(self) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get("/health/live")
            response.raise_for_status()

    async def get_transaction_history(
        self, *, given_name: str, family_name: str, synthetic_id: str, declared_annual_income: int
    ) -> TransactionHistory:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(
                "/transaction-history",
                json={
                    "given_name": given_name,
                    "family_name": family_name,
                    "synthetic_id": synthetic_id,
                    "declared_annual_income": declared_annual_income,
                },
            )
            response.raise_for_status()
            body = response.json()
            return TransactionHistory(
                average_daily_balance_cents=body["average_daily_balance_cents"],
                nsf_count_last_90_days=body["nsf_count_last_90_days"],
                recent_transactions=[
                    Transaction(
                        occurred_at=datetime.fromisoformat(t["occurred_at"]),
                        amount_cents=t["amount_cents"],
                        description=t["description"],
                    )
                    for t in body["recent_transactions"]
                ],
            )
