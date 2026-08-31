"""Synthetic core-banking transaction history generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from services.synthetic_data.applicants import SyntheticApplicant
from services.synthetic_data.rng import rng_for

_DAYS_OF_HISTORY = 90

# Deterministic anchor for "now" -- using the real wall clock here would break the
# same-inputs-same-output guarantee every other generator in this package provides (a bug this
# module's own test suite caught: two calls with identical arguments produced different
# timestamps). Callers that want dates near the real present can pass `reference_time` explicitly.
_DEFAULT_REFERENCE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Transaction:
    occurred_at: datetime
    amount: int
    """Cents; negative for debits, positive for credits."""
    description: str


@dataclass(frozen=True, slots=True)
class SyntheticTransactionHistory:
    applicant_synthetic_id: str
    average_daily_balance: int
    """Cents."""
    nsf_count_last_90_days: int
    transactions: tuple[Transaction, ...] = field(default_factory=tuple)


def generate_transaction_history(
    applicant: SyntheticApplicant,
    scenario_id: str,
    index: int = 0,
    *,
    reference_time: datetime | None = None,
) -> SyntheticTransactionHistory:
    rng = rng_for(f"transactions:{scenario_id}:{applicant.synthetic_id}", index)
    now = reference_time or _DEFAULT_REFERENCE_TIME

    low_balance = scenario_id == "LOW_BALANCE_NSF"
    starting_balance = rng.randint(5_000, 20_000) if low_balance else rng.randint(150_000, 900_000)
    nsf_count = rng.randint(3, 8) if low_balance else 0

    transactions: list[Transaction] = []
    balance = starting_balance
    for day_offset in range(_DAYS_OF_HISTORY):
        occurred_at = now - timedelta(days=_DAYS_OF_HISTORY - day_offset)
        if day_offset % 14 == 0:
            amount = int(applicant.declared_annual_income / 26 * 100)
            transactions.append(
                Transaction(occurred_at=occurred_at, amount=amount, description="Payroll deposit")
            )
            balance += amount
        if rng.random() < 0.3:
            amount = -rng.randint(500, 20_000)
            transactions.append(
                Transaction(occurred_at=occurred_at, amount=amount, description="Card purchase")
            )
            balance += amount

    return SyntheticTransactionHistory(
        applicant_synthetic_id=applicant.synthetic_id,
        average_daily_balance=max(balance, 0),
        nsf_count_last_90_days=nsf_count,
        transactions=tuple(transactions),
    )
