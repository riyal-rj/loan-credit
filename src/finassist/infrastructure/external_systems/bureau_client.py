"""`HttpBureauClient`: the `BureauClient` port's adapter for `services/mock-bureau` (Phase 2)."""

from __future__ import annotations

from datetime import date

import httpx

from finassist.application.ports.external_verification import BureauClient, CreditReport, Tradeline


class HttpBureauClient(BureauClient):
    def __init__(self, *, base_url: str, request_timeout_seconds: float) -> None:
        self._base_url = base_url
        self._timeout = httpx.Timeout(request_timeout_seconds)

    async def check_connectivity(self) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get("/health/live")
            response.raise_for_status()

    async def get_credit_report(
        self, *, given_name: str, family_name: str, date_of_birth: date, synthetic_id: str
    ) -> CreditReport:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(
                "/credit-report",
                json={
                    "given_name": given_name,
                    "family_name": family_name,
                    "date_of_birth": date_of_birth.isoformat(),
                    "synthetic_id": synthetic_id,
                },
            )
            response.raise_for_status()
            body = response.json()
            return CreditReport(
                credit_score=body["credit_score"],
                tradelines=[
                    Tradeline(
                        account_type=t["account_type"],
                        opened_years_ago=t["opened_years_ago"],
                        balance=t["balance"],
                        credit_limit=t["credit_limit"],
                        is_delinquent=t["is_delinquent"],
                    )
                    for t in body["tradelines"]
                ],
                hard_inquiries_last_12_months=body["hard_inquiries_last_12_months"],
                is_duplicate_identity_flag=body["is_duplicate_identity_flag"],
            )
