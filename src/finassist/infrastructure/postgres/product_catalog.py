"""SQLAlchemy-backed `ProductCatalog` adapter -- read-only access to the seeded product catalog."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.application.ports.product_catalog import ProductCatalog
from finassist.domain.applications.product import Product
from finassist.domain.shared.identifiers import ProductId
from finassist.domain.shared.money import Money
from finassist.infrastructure.postgres.orm_models import ProductRow


def _row_to_product(row: ProductRow) -> Product:
    return Product(
        product_id=ProductId(row.product_id),
        code=row.code,
        name=row.name,
        currency=row.currency,
        min_amount=Money(row.min_amount, row.currency),
        max_amount=Money(row.max_amount, row.currency),
        min_term_months=row.min_term_months,
        max_term_months=row.max_term_months,
        is_active=row.is_active,
    )


class SqlAlchemyProductCatalog(ProductCatalog):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, product_id: ProductId) -> Product | None:
        row = await self._session.get(ProductRow, str(product_id))
        return _row_to_product(row) if row is not None else None

    async def get_by_code(self, *, code: str) -> Product | None:
        result = await self._session.execute(select(ProductRow).where(ProductRow.code == code))
        row = result.scalar_one_or_none()
        return _row_to_product(row) if row is not None else None
