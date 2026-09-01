"""Ports for the four synthetic external systems (Phase 2's mock LOS/KYC/bureau/employer/
core-banking, minus LOS -- workers augment an origination system, master instruction §3, and this
build never becomes one). One Protocol per service, each with exactly the one method that
service's one real endpoint offers, mirroring `object_store.py`'s narrow-port convention.

Result dataclasses mirror each mock service's response schema (`services/mock-*/main.py`) field
for field, translated into this port's own types rather than passed through as raw dicts --
`finassist.application` may not import the `services/` mock apps directly (those are test/demo
tooling, docs/adr/0010 decision 1), so this is the boundary where a mock response becomes a typed
value the rest of the application layer can depend on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class KycVerificationResult:
    status: str
    name_match_score: float
    address_match_score: float
    date_of_birth_match: bool
    reference_id: str


@runtime_checkable
class KycVerifier(Protocol):
    async def check_connectivity(self) -> None: ...

    async def verify_identity(
        self,
        *,
        given_name: str,
        family_name: str,
        date_of_birth: date,
        synthetic_id: str,
        street_address: str,
        city: str,
    ) -> KycVerificationResult: ...


@dataclass(frozen=True, slots=True)
class EmploymentVerificationResult:
    is_employment_confirmed: bool
    verified_annual_income: int
    tenure_months: int


@runtime_checkable
class EmployerVerifier(Protocol):
    async def check_connectivity(self) -> None: ...

    async def verify_employment(
        self,
        *,
        given_name: str,
        family_name: str,
        synthetic_id: str,
        employer_name: str,
        declared_annual_income: int,
    ) -> EmploymentVerificationResult: ...


@dataclass(frozen=True, slots=True)
class Tradeline:
    account_type: str
    opened_years_ago: int
    balance: int
    credit_limit: int
    is_delinquent: bool


@dataclass(frozen=True, slots=True)
class CreditReport:
    credit_score: int
    tradelines: list[Tradeline]
    hard_inquiries_last_12_months: int
    is_duplicate_identity_flag: bool


@runtime_checkable
class BureauClient(Protocol):
    async def check_connectivity(self) -> None: ...

    async def get_credit_report(
        self, *, given_name: str, family_name: str, date_of_birth: date, synthetic_id: str
    ) -> CreditReport: ...


@dataclass(frozen=True, slots=True)
class Transaction:
    occurred_at: datetime
    amount_cents: int
    description: str


@dataclass(frozen=True, slots=True)
class TransactionHistory:
    average_daily_balance_cents: int
    nsf_count_last_90_days: int
    recent_transactions: list[Transaction]


@runtime_checkable
class CoreBankingClient(Protocol):
    async def check_connectivity(self) -> None: ...

    async def get_transaction_history(
        self, *, given_name: str, family_name: str, synthetic_id: str, declared_annual_income: int
    ) -> TransactionHistory: ...
