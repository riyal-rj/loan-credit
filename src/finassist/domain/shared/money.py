"""Currency-aware, decimal-only money value object.

Master instruction §5.5/§10.1: "Affordability calculations must use typed decimal arithmetic
... never binary floating-point for money" and "Store money as NUMERIC with currency; never
float." This type is the single point where that rule is enforced -- no other module constructs
a monetary amount without going through it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

_SUPPORTED_CURRENCIES = frozenset({"USD", "EUR"})
"""Deliberately narrow for the Phase 0 scope (the one seeded product is USD-only, per
docs/architecture/phase-0-assessment.md assumption A1). EUR is included even though no product
uses it yet specifically so the cross-currency safety checks below are exercised by real tests
now rather than being unreachable dead code until Phase 5's multi-currency affordability work."""

_MINOR_UNIT_EXPONENTS: dict[str, int] = {"USD": 2, "EUR": 2}


class UnsupportedCurrencyError(ValueError):
    """Raised when a `Money` value is constructed with a currency this build does not support."""

    def __init__(self, currency: str) -> None:
        super().__init__(
            f"currency {currency!r} is not in the supported set {sorted(_SUPPORTED_CURRENCIES)}"
        )


class CurrencyMismatchError(ValueError):
    """Raised when an arithmetic operation is attempted between two different currencies."""

    def __init__(self, left: str, right: str) -> None:
        super().__init__(f"cannot combine {left!r} and {right!r} amounts")


@dataclass(frozen=True, slots=True)
class Money:
    """An immutable amount in a specific ISO 4217 currency, backed by `Decimal`.

    Construction always quantizes to the currency's minor unit using round-half-even (banker's
    rounding), so two `Money` values that print the same are guaranteed equal -- there is no
    "0.005 vs 0.0050000001" class of bug possible here.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.currency not in _SUPPORTED_CURRENCIES:
            raise UnsupportedCurrencyError(self.currency)
        exponent = _MINOR_UNIT_EXPONENTS[self.currency]
        quantized = self.amount.quantize(Decimal(1).scaleb(-exponent), rounding=ROUND_HALF_EVEN)
        object.__setattr__(self, "amount", quantized)

    @classmethod
    def of(cls, amount: str | int | Decimal, currency: str) -> Money:
        """Construct from a string/int/Decimal, avoiding float entirely at the call site."""
        return cls(Decimal(amount), currency)

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency)

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount >= other.amount

    def is_negative(self) -> bool:
        return self.amount < 0

    def is_zero(self) -> bool:
        return self.amount == 0
