"""Outbox -> Kafka relay (Phase 3, docs/adr/0011).

Polls each tenant's `integration.outbox_events` (`published_at IS NULL`) in its own short-lived,
RLS-scoped session -- `SET LOCAL app.tenant_id`, the exact mechanism `SqlAlchemyUnitOfWork`
already uses -- never a superuser/BYPASSRLS connection. `identity.tenants` is the one table with
no RLS policy, so it is the source of the tenant list to iterate. `FOR UPDATE SKIP LOCKED` makes a
sweep safe to run from more than one relay instance concurrently.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.infrastructure.kafka.producer import KafkaEventProducer
from finassist.infrastructure.postgres.orm_models import OutboxEventRow

_PRODUCER_NAME = "finassist-api"
_DATA_CLASSIFICATION = "internal"
"""Constant for now: these envelopes carry only status/product-id/document-metadata fields, never
document content or free-text PII (master instruction §12: "Do not place full document content,
unrestricted PII ... in Kafka messages")."""


async def _list_tenant_ids(session: AsyncSession) -> list[str]:
    result = await session.execute(text("SELECT tenant_id FROM identity.tenants"))
    return [row[0] for row in result.all()]


def _build_envelope(row: OutboxEventRow) -> dict[str, object]:
    return {
        "event_id": row.event_id,
        "event_type": row.event_type,
        "schema_version": row.schema_version,
        "occurred_at": row.occurred_at.isoformat(),
        "producer": _PRODUCER_NAME,
        "tenant_id": row.tenant_id,
        "application_id": row.aggregate_id,
        "correlation_id": row.correlation_id,
        "causation_id": row.causation_id,
        "traceparent": None,
        "data_classification": _DATA_CLASSIFICATION,
        "payload": row.payload,
    }


async def _relay_tenant_batch(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: str,
    producer: KafkaEventProducer,
    batch_size: int,
) -> int:
    async with session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        result = await session.execute(
            select(OutboxEventRow)
            .where(OutboxEventRow.tenant_id == tenant_id, OutboxEventRow.published_at.is_(None))
            .order_by(OutboxEventRow.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars().all())
        for row in rows:
            envelope = _build_envelope(row)
            await producer.publish(key=row.aggregate_id, value=json.dumps(envelope).encode())
            row.published_at = datetime.now(UTC)
        await session.commit()
        return len(rows)


async def relay_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    producer: KafkaEventProducer,
    batch_size: int,
) -> int:
    """One full sweep across every tenant. Returns the total number of events published."""
    async with session_factory() as session:
        tenant_ids = await _list_tenant_ids(session)
    total = 0
    for tenant_id in tenant_ids:
        total += await _relay_tenant_batch(
            session_factory=session_factory,
            tenant_id=tenant_id,
            producer=producer,
            batch_size=batch_size,
        )
    return total


async def unpublished_backlog_size(*, session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Total unpublished outbox rows across every tenant (ADR-0009's flagged Phase 3 bounded-
    backlog check). Must iterate per tenant like the relay does: under `FORCE ROW LEVEL SECURITY`,
    a session with no `app.tenant_id` set matches zero rows (`tenant_id = NULL` is never true),
    which would silently under-report as "no backlog" rather than raising -- there is no
    "read across every tenant" query this table's RLS policy permits."""
    async with session_factory() as session:
        tenant_ids = await _list_tenant_ids(session)
    total = 0
    for tenant_id in tenant_ids:
        async with session_factory() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            result = await session.execute(
                select(func.count())
                .select_from(OutboxEventRow)
                .where(
                    OutboxEventRow.tenant_id == tenant_id, OutboxEventRow.published_at.is_(None)
                )
            )
            total += int(result.scalar_one())
    return total
