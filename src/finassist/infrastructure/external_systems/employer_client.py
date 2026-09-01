"""`HttpEmployerVerifier`: the `EmployerVerifier` port's adapter for `services/mock-employer`
(Phase 2)."""

from __future__ import annotations

import httpx

from finassist.application.ports.external_verification import (
    EmployerVerifier,
    EmploymentVerificationResult,
)


class HttpEmployerVerifier(EmployerVerifier):
    def __init__(self, *, base_url: str, request_timeout_seconds: float) -> None:
        self._base_url = base_url
        self._timeout = httpx.Timeout(request_timeout_seconds)

    async def check_connectivity(self) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get("/health/live")
            response.raise_for_status()

    async def verify_employment(
        self,
        *,
        given_name: str,
        family_name: str,
        synthetic_id: str,
        employer_name: str,
        declared_annual_income: int,
    ) -> EmploymentVerificationResult:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(
                "/verify-employment",
                json={
                    "given_name": given_name,
                    "family_name": family_name,
                    "synthetic_id": synthetic_id,
                    "employer_name": employer_name,
                    "declared_annual_income": declared_annual_income,
                },
            )
            response.raise_for_status()
            body = response.json()
            return EmploymentVerificationResult(
                is_employment_confirmed=body["is_employment_confirmed"],
                verified_annual_income=body["verified_annual_income"],
                tenure_months=body["tenure_months"],
            )
