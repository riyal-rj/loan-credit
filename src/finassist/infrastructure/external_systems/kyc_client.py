"""`HttpKycVerifier`: the `KycVerifier` port's adapter for `services/mock-kyc` (Phase 2)."""

from __future__ import annotations

from datetime import date

import httpx

from finassist.application.ports.external_verification import KycVerificationResult, KycVerifier


class HttpKycVerifier(KycVerifier):
    def __init__(self, *, base_url: str, request_timeout_seconds: float) -> None:
        self._base_url = base_url
        self._timeout = httpx.Timeout(request_timeout_seconds)

    async def check_connectivity(self) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get("/health/live")
            response.raise_for_status()

    async def verify_identity(
        self,
        *,
        given_name: str,
        family_name: str,
        date_of_birth: date,
        synthetic_id: str,
        street_address: str,
        city: str,
    ) -> KycVerificationResult:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(
                "/verify",
                json={
                    "given_name": given_name,
                    "family_name": family_name,
                    "date_of_birth": date_of_birth.isoformat(),
                    "synthetic_id": synthetic_id,
                    "street_address": street_address,
                    "city": city,
                },
            )
            response.raise_for_status()
            body = response.json()
            return KycVerificationResult(
                status=body["status"],
                name_match_score=body["name_match_score"],
                address_match_score=body["address_match_score"],
                date_of_birth_match=body["date_of_birth_match"],
                reference_id=body["reference_id"],
            )
