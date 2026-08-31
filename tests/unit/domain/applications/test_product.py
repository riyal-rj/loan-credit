from __future__ import annotations

import pytest

from finassist.domain.applications.product import Product
from finassist.domain.shared.identifiers import ProductId, new_id
from finassist.domain.shared.money import Money


def _product(**overrides: object) -> Product:
    defaults: dict[str, object] = {
        "product_id": ProductId(new_id()),
        "code": "PERSONAL_LOAN_USD",
        "name": "Personal Loan",
        "currency": "USD",
        "min_amount": Money.of("1000.00", "USD"),
        "max_amount": Money.of("25000.00", "USD"),
        "min_term_months": 6,
        "max_term_months": 60,
        "is_active": True,
    }
    defaults.update(overrides)
    return Product(**defaults)  # type: ignore[arg-type]


def test_accepts_amount_and_term_within_bounds() -> None:
    product = _product()
    assert product.accepts(Money.of("5000.00", "USD"), 24)


def test_rejects_amount_below_minimum() -> None:
    product = _product()
    assert not product.accepts(Money.of("500.00", "USD"), 24)


def test_rejects_amount_above_maximum() -> None:
    product = _product()
    assert not product.accepts(Money.of("30000.00", "USD"), 24)


def test_rejects_term_outside_bounds() -> None:
    product = _product()
    assert not product.accepts(Money.of("5000.00", "USD"), 3)
    assert not product.accepts(Money.of("5000.00", "USD"), 72)


def test_rejects_inactive_product() -> None:
    product = _product(is_active=False)
    assert not product.accepts(Money.of("5000.00", "USD"), 24)


def test_rejects_wrong_currency() -> None:
    product = _product()
    assert not product.accepts(Money.of("5000.00", "EUR"), 24)


def test_rejects_min_amount_exceeding_max_amount() -> None:
    with pytest.raises(ValueError, match="min_amount must not exceed max_amount"):
        _product(min_amount=Money.of("30000.00", "USD"), max_amount=Money.of("1000.00", "USD"))


def test_rejects_min_term_exceeding_max_term() -> None:
    with pytest.raises(ValueError, match="min_term_months must not exceed max_term_months"):
        _product(min_term_months=60, max_term_months=6)


def test_rejects_amount_bounds_in_wrong_currency() -> None:
    with pytest.raises(ValueError, match="product's currency"):
        _product(min_amount=Money.of("1000.00", "EUR"))
