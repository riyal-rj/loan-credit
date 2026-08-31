"""Outbox -> Kafka relay integration tests (Phase 3, docs/adr/0011): real PostgreSQL (via
`tests/integration/conftest.py`) and a real, disposable Kafka broker (testcontainers).

Two tenants, proving the relay's per-tenant `SET LOCAL app.tenant_id` iteration publishes each
tenant's own rows under its own scope (never a superuser/BYPASSRLS connection), marks
`published_at`, and that the backlog check accounts for every tenant.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.community.kafka import KafkaContainer

from finassist.application.commands.create_application import (
    CreateApplicationCommand,
    CreateApplicationHandler,
)
from finassist.application.commands.submit_application import (
    SubmitApplicationCommand,
    SubmitApplicationHandler,
)
from finassist.application.ports.id_generator import UuidIdGenerator
from finassist.domain.shared.clock import FixedClock
from finassist.domain.shared.identifiers import ProductId, TenantId, new_id
from finassist.domain.shared.money import Money
from finassist.infrastructure.kafka.outbox_relay import relay_once, unpublished_backlog_size
from finassist.infrastructure.kafka.producer import KafkaEventProducer
from finassist.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWorkFactory

from .test_application_repository import _seed_tenant_and_product

pytestmark = pytest.mark.asyncio(loop_scope="session")

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_TOPIC = "finassist.applications.events.test"


@pytest.fixture(scope="session")
def kafka_bootstrap_servers() -> Iterator[str]:
    with KafkaContainer() as kafka:
        yield kafka.get_bootstrap_server()


@pytest_asyncio.fixture(loop_scope="session")
async def kafka_producer(kafka_bootstrap_servers: str) -> AsyncIterator[KafkaEventProducer]:
    producer = KafkaEventProducer(
        bootstrap_servers=kafka_bootstrap_servers,
        security_protocol="PLAINTEXT",
        topic=_TOPIC,
    )
    await producer.ensure_ready()
    yield producer
    await producer.close()


async def _create_and_submit(
    session_factory: async_sessionmaker[AsyncSession], tenant_id: str, product_id: str
) -> str:
    uow_factory = SqlAlchemyUnitOfWorkFactory(
        session_factory, clock=FixedClock(_NOW), id_generator=UuidIdGenerator()
    )
    create_result = await CreateApplicationHandler(
        uow_factory=uow_factory, id_generator=UuidIdGenerator(), clock=FixedClock(_NOW)
    ).handle(
        CreateApplicationCommand(
            tenant_id=TenantId(tenant_id),
            idempotency_key=new_id(),
            applicant_given_name="Ada",
            applicant_family_name="Lovelace",
            applicant_date_of_birth=date(1990, 1, 1),
            applicant_email="ada@example.test",
            product_id=ProductId(product_id),
            requested_amount=Money.of("5000.00", "USD"),
            requested_term_months=24,
        )
    )
    await SubmitApplicationHandler(uow_factory=uow_factory, clock=FixedClock(_NOW)).handle(
        SubmitApplicationCommand(
            tenant_id=TenantId(tenant_id),
            application_id=create_result.application_id,
            idempotency_key=new_id(),
        )
    )
    return str(create_result.application_id)


async def test_relay_publishes_both_tenants_and_marks_published(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
    kafka_producer: KafkaEventProducer,
    kafka_bootstrap_servers: str,
) -> None:
    tenant_a, product_a = new_id(), new_id()
    tenant_b, product_b = new_id(), new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_a, product_id=product_a
    )
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_b, product_id=product_b
    )

    app_a = await _create_and_submit(session_factory, tenant_a, product_a)
    app_b = await _create_and_submit(session_factory, tenant_b, product_b)

    backlog_before = await unpublished_backlog_size(session_factory=session_factory)
    assert backlog_before >= 4  # 2 events per application (Created + StateChanged), 2 apps

    published = await relay_once(
        session_factory=session_factory, producer=kafka_producer, batch_size=100
    )
    assert published >= 4

    backlog_after = await unpublished_backlog_size(session_factory=session_factory)
    assert backlog_after == 0

    consumer = AIOKafkaConsumer(
        _TOPIC,
        bootstrap_servers=kafka_bootstrap_servers,
        auto_offset_reset="earliest",
        group_id=f"test-consumer-{new_id()}",
    )
    await consumer.start()
    try:
        seen: dict[str, list[dict[str, object]]] = {tenant_a: [], tenant_b: []}
        deadline_batches = 0
        while (len(seen[tenant_a]) < 2 or len(seen[tenant_b]) < 2) and deadline_batches < 20:
            batches = await consumer.getmany(timeout_ms=1000, max_records=50)
            for records in batches.values():
                for record in records:
                    envelope = json.loads(record.value)
                    tenant = envelope["tenant_id"]
                    if tenant in seen:
                        seen[tenant].append(envelope)
            deadline_batches += 1
    finally:
        await consumer.stop()

    assert len(seen[tenant_a]) == 2
    assert len(seen[tenant_b]) == 2
    assert all(e["application_id"] == app_a for e in seen[tenant_a])
    assert all(e["application_id"] == app_b for e in seen[tenant_b])
    assert {e["event_type"] for e in seen[tenant_a]} == {
        "ApplicationCreated",
        "ApplicationStateChanged",
    }
