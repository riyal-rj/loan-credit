from __future__ import annotations

from decimal import Decimal

import pytest

from finassist.domain.shared.money import CurrencyMismatchError, Money, UnsupportedCurrencyError


def test_quantizes_to_minor_unit_with_banker_rounding() -> None:
    assert Money.of("10.005", "USD").amount == Decimal("10.00")
    assert Money.of("10.015", "USD").amount == Decimal("10.02")


def test_rejects_unsupported_currency() -> None:
    with pytest.raises(UnsupportedCurrencyError):
        Money.of("10.00", "XYZ")


def test_addition_and_subtraction() -> None:
    a = Money.of("10.00", "USD")
    b = Money.of("2.50", "USD")
    assert a + b == Money.of("12.50", "USD")
    assert a - b == Money.of("7.50", "USD")


def test_cross_currency_arithmetic_rejected() -> None:
    usd = Money.of("10.00", "USD")
    eur = Money.of("10.00", "EUR")
    with pytest.raises(CurrencyMismatchError):
        _ = usd + eur
    with pytest.raises(CurrencyMismatchError):
        _ = usd - eur
    with pytest.raises(CurrencyMismatchError):
        _ = usd < eur


def test_ordering() -> None:
    small = Money.of("5.00", "USD")
    large = Money.of("10.00", "USD")
    assert small < large
    assert large > small
    assert small <= small
    assert large >= large


def test_is_negative_and_is_zero() -> None:
    assert Money.of("-1.00", "USD").is_negative()
    assert Money.of("0.00", "USD").is_zero()
    assert not Money.of("1.00", "USD").is_zero()
