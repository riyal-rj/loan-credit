"""`KafkaProjectionConsumer` integration tests (Phase 3, docs/adr/0011): real PostgreSQL + a real,
disposable Kafka broker.

Proves the full outbox-shape -> Kafka -> inbox-dedup -> `applications.status_projection` loop, and
that redelivering the identical `event_id` (e.g. a relay retry, or a consumer crash before
committing its offset) does not double-apply -- the first real exercise of `integration.
inbox_messages`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from aiokafka import AIOKafkaProducer
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.community.kafka import KafkaContainer

from finassist.domain.shared.identifiers import new_id
from finassist.infrastructure.kafka.projection_consumer import run_projection_consumer
from finassist.infrastructure.postgres.orm_models import InboxMessageRow, StatusProjectionRow

from .test_application_repository import _seed_tenant_and_product

pytestmark = pytest.mark.asyncio(loop_scope="session")

_TOPIC = "finassist.applications.events.projection-test"
_CONSUMER_GROUP = "applications-projection-test"
_POLL_TIMEOUT_SECONDS = 20.0


@pytest.fixture(scope="session")
def kafka_bootstrap_servers() -> Iterator[str]:
    with KafkaContainer() as kafka:
        yield kafka.get_bootstrap_server()


def _envelope(*, event_id: str, tenant_id: str, application_id: str) -> dict[str, object]:
    return {
        "event_id": event_id,
        "event_type": "ApplicationCreated",
        "schema_version": 1,
        "occurred_at": datetime.now(UTC).isoformat(),
        "producer": "test",
        "tenant_id": tenant_id,
        "application_id": application_id,
        "correlation_id": None,
        "causation_id": None,
        "traceparent": None,
        "data_classification": "internal",
        "payload": {"product_id": new_id()},
    }


async def _wait_for_projection_row(
    session_factory: async_sessionmaker[AsyncSession], *, tenant_id: str, application_id: str
) -> StatusProjectionRow:
    deadline = asyncio.get_event_loop().time() + _POLL_TIMEOUT_SECONDS
    while asyncio.get_event_loop().time() < deadline:
        async with session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id}
            )
            row = await session.get(StatusProjectionRow, application_id)
            if row is not None:
                return row
        await asyncio.sleep(0.5)
    raise AssertionError("projection row never appeared within the poll timeout")


async def test_duplicate_event_id_redelivery_does_not_double_apply(
    session_factory: async_sessionmaker[AsyncSession],
    admin_session_factory: async_sessionmaker[AsyncSession],
    kafka_bootstrap_servers: str,
) -> None:
    tenant_id, product_id = new_id(), new_id()
    await _seed_tenant_and_product(
        session_factory, admin_session_factory, tenant_id=tenant_id, product_id=product_id
    )
    application_id = new_id()
    event_id = new_id()
    envelope = _envelope(event_id=event_id, tenant_id=tenant_id, application_id=application_id)

    producer = AIOKafkaProducer(bootstrap_servers=kafka_bootstrap_servers)
    await producer.start()
    try:
        payload = json.dumps(envelope).encode()
        # Publish the *same* event_id twice -- simulates a relay/consumer redelivery, not two
        # different real events.
        await producer.send_and_wait(_TOPIC, value=payload, key=application_id.encode())
        await producer.send_and_wait(_TOPIC, value=payload, key=application_id.encode())
    finally:
        await producer.stop()

    stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(
        run_projection_consumer(
            bootstrap_servers=kafka_bootstrap_servers,
            security_protocol="PLAINTEXT",
            topic=_TOPIC,
            consumer_group=_CONSUMER_GROUP,
            session_factory=session_factory,
            stop_signal=stop_event,
        )
    )
    try:
        row = await _wait_for_projection_row(
            session_factory, tenant_id=tenant_id, application_id=application_id
        )
        assert row.status == "DRAFT"
        assert row.version == 1

        # Give the consumer a moment to also process the second (duplicate) message, which was
        # produced before the first was ever consumed.
        await asyncio.sleep(2.0)
    finally:
        stop_event.set()
        await asyncio.wait_for(consumer_task, timeout=15.0)

    async with session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id}
        )
        inbox_count = (
            await session.execute(
                select(func.count())
                .select_from(InboxMessageRow)
                .where(InboxMessageRow.event_id == event_id)
            )
        ).scalar_one()
        projection_row = await session.get(StatusProjectionRow, application_id)

    assert inbox_count == 1
    assert projection_row is not None
    assert projection_row.status == "DRAFT"
    assert projection_row.version == 1
