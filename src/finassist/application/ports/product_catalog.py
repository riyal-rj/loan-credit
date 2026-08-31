"""Port for read-only access to the product catalog.

Products are reference/configuration data (seeded via migration, docs/adr/0009), not synthetic
applicant data -- there is deliberately no `add`/`save` here yet. Product authoring becomes a real
admin use case when Phase 5's policy/product versioning lands.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from finassist.domain.applications.product import Product
from finassist.domain.shared.identifiers import ProductId


@runtime_checkable
class ProductCatalog(Protocol):
    async def get(self, *, product_id: ProductId) -> Product | None: ...

    async def get_by_code(self, *, code: str) -> Product | None: ...
