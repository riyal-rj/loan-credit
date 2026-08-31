"""The `Product` entity: catalog bounds for a lending product.

Phase 1B scope is exactly one product (docs/architecture/phase-0-assessment.md assumption A1:
an unsecured consumer personal loan). `Product` exists as a real, referenced type from the first
commit so a second product is a new row, never a code branch. Full policy/rate-band evaluation is
Phase 5 -- this entity only carries the catalog bounds needed to reject an obviously out-of-range
request at intake (§9 Intake Agent: "validate completeness ... identify missing items", not decide
eligibility).
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.domain.shared.identifiers import ProductId
from finassist.domain.shared.money import Money


@dataclass(frozen=True, slots=True)
class Product:
    product_id: ProductId
    code: str
    name: str
    currency: str
    min_amount: Money
    max_amount: Money
    min_term_months: int
    max_term_months: int
    is_active: bool

    def __post_init__(self) -> None:
        if self.min_amount.currency != self.currency or self.max_amount.currency != self.currency:
            raise ValueError("product amount bounds must be denominated in the product's currency")
        if self.min_amount > self.max_amount:
            raise ValueError("product min_amount must not exceed max_amount")
        if self.min_term_months < 1:
            raise ValueError("product min_term_months must be at least 1")
        if self.min_term_months > self.max_term_months:
            raise ValueError("product min_term_months must not exceed max_term_months")

    def accepts(self, amount: Money, term_months: int) -> bool:
        """Whether ``amount``/``term_months`` fall within this product's catalog bounds.

        This is a coarse intake check, not a policy decision -- a request this method accepts can
        still be declined by the deterministic policy engine (Phase 5).
        """
        if not self.is_active:
            return False
        if amount.currency != self.currency:
            return False
        return self.min_amount <= amount <= self.max_amount and (
            self.min_term_months <= term_months <= self.max_term_months
        )
