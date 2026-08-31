from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from finassist.application.commands.create_application import (
    CreateApplicationCommand,
    CreateApplicationHandler,
)
from finassist.domain.applications.exceptions import (
    DuplicateRequestError,
    ProductNotFoundError,
    ProductRejectedRequestError,
)
from finassist.domain.applications.product import Product
from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import ProductId, TenantId, new_id
from finassist.domain.shared.money import Money

from ._fakes import FakeUnitOfWorkFactory, FixedIdGenerator

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _product(product_id: str) -> Product:
    return Product(
        product_id=ProductId(product_id),
        code="PERSONAL_LOAN_USD",
        name="Personal Loan",
        currency="USD",
        min_amount=Money.of("1000.00", "USD"),
        max_amount=Money.of("25000.00", "USD"),
        min_term_months=6,
        max_term_months=60,
        is_active=True,
    )


def _handler(
    product: Product, ids: list[str], uow_factory: FakeUnitOfWorkFactory | None = None
) -> tuple[CreateApplicationHandler, FakeUnitOfWorkFactory]:
    factory = uow_factory or FakeUnitOfWorkFactory(products=[product])
    handler = CreateApplicationHandler(
        uow_factory=factory,
        id_generator=FixedIdGenerator(ids),
        clock=FixedClock(_NOW),
    )
    return handler, factory


def _command(
    tenant_id: TenantId, product_id: str, idempotency_key: str
) -> CreateApplicationCommand:
    return CreateApplicationCommand(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        applicant_given_name="Ada",
        applicant_family_name="Lovelace",
        applicant_date_of_birth=date(1990, 1, 1),
        applicant_email="ada@example.test",
        product_id=ProductId(product_id),
        requested_amount=Money.of("5000.00", "USD"),
        requested_term_months=24,
    )


@pytest.mark.asyncio
async def test_creates_application_and_applicant_in_draft() -> None:
    product_id = new_id()
    tenant_id = TenantId(new_id())
    application_id, applicant_id = new_id(), new_id()
    handler, factory = _handler(_product(product_id), ids=[applicant_id, application_id])

    result = await handler.handle(_command(tenant_id, product_id, "key-1"))

    assert result.status is ApplicationStatus.DRAFT
    assert result.version == 1
    stored = factory.store.applications[(str(tenant_id), str(result.application_id))]
    assert stored.applicant_id == result.applicant_id
    assert factory.store.applicants[(str(tenant_id), str(result.applicant_id))].given_name == "Ada"


@pytest.mark.asyncio
async def test_records_domain_event_and_commits() -> None:
    product_id = new_id()
    tenant_id = TenantId(new_id())
    handler, factory = _handler(_product(product_id), ids=[new_id(), new_id()])

    await handler.handle(_command(tenant_id, product_id, "key-1"))

    assert len(factory.store.recorded_events) == 1


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_is_rejected() -> None:
    product_id = new_id()
    tenant_id = TenantId(new_id())
    handler, factory = _handler(_product(product_id), ids=[new_id(), new_id(), new_id(), new_id()])

    await handler.handle(_command(tenant_id, product_id, "same-key"))

    with pytest.raises(DuplicateRequestError):
        await handler.handle(_command(tenant_id, product_id, "same-key"))


@pytest.mark.asyncio
async def test_unknown_product_is_rejected() -> None:
    handler, _ = _handler(_product(new_id()), ids=[new_id(), new_id()])

    with pytest.raises(ProductNotFoundError):
        await handler.handle(_command(TenantId(new_id()), new_id(), "key-1"))


@pytest.mark.asyncio
async def test_amount_outside_product_bounds_is_rejected() -> None:
    product_id = new_id()
    tenant_id = TenantId(new_id())
    handler, _ = _handler(_product(product_id), ids=[new_id(), new_id()])
    command = CreateApplicationCommand(
        tenant_id=tenant_id,
        idempotency_key="key-1",
        applicant_given_name="Ada",
        applicant_family_name="Lovelace",
        applicant_date_of_birth=date(1990, 1, 1),
        applicant_email="ada@example.test",
        product_id=ProductId(product_id),
        requested_amount=Money.of("100.00", "USD"),
        requested_term_months=24,
    )

    with pytest.raises(ProductRejectedRequestError):
        await handler.handle(command)
