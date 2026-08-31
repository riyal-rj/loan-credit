"""`KafkaProjectionConsumer`: maintains `applications.status_projection` from the
`finassist.applications.events` topic (Phase 3, docs/adr/0011).

The first real consumer of `integration.inbox_messages`: one row per `(event_id, consumer_name)`
is inserted before applying an event, and a unique-violation on that insert means "already
applied, skip" -- the same insert-and-catch-conflict shape `reserve_idempotency_key` already uses,
applied to consumer-side dedup instead of command-side idempotency. Kafka offsets are committed
manually, only after the DB transaction that applied (or deduped) the message has committed, so a
worker crash between "message consumed" and "offset committed" reprocesses the message rather than
losing it -- redelivery is exactly what the inbox check is for.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaConsumer
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finassist.bootstrap.logging import get_logger
from finassist.infrastructure.postgres.orm_models import InboxMessageRow, StatusProjectionRow

logger = get_logger(__name__)

_PROJECTED_EVENT_TYPES = frozenset({"ApplicationCreated", "ApplicationStateChanged"})


async def _apply_event(
    *, session: AsyncSession, envelope: dict[str, Any], consumer_name: str
) -> bool:
    """Returns True if this event was newly applied, False if it was a deduped redelivery."""
    session.add(
        InboxMessageRow(
            event_id=envelope["event_id"],
            consumer_name=consumer_name,
            processed_at=datetime.now(UTC),
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return False

    if envelope["event_type"] in _PROJECTED_EVENT_TYPES:
        application_id = envelope["application_id"]
        row = await session.get(StatusProjectionRow, application_id)
        occurred_at = datetime.fromisoformat(envelope["occurred_at"])
        if envelope["event_type"] == "ApplicationCreated":
            status, version = "DRAFT", 1
        else:
            status = envelope["payload"]["new_status"]
            version = envelope["payload"]["version"]

        if row is None:
            session.add(
                StatusProjectionRow(
                    application_id=application_id,
                    tenant_id=envelope["tenant_id"],
                    status=status,
                    version=version,
                    updated_at=occurred_at,
                )
            )
        elif version >= row.version:
            # Kafka guarantees ordering only within one partition; events are keyed by
            # application_id so same-application events are ordered, but guard against an
            # out-of-order redelivery regressing the projection anyway.
            row.status = status
            row.version = version
            row.updated_at = occurred_at
    await session.commit()
    return True


async def run_projection_consumer(
    *,
    bootstrap_servers: str,
    security_protocol: str,
    topic: str,
    consumer_group: str,
    session_factory: async_sessionmaker[AsyncSession],
    stop_signal: asyncio.Event,
) -> None:
    """Runs until ``stop_signal`` (an `asyncio.Event`) is set. Each message: set the message's
    tenant into RLS scope, apply-or-dedupe, commit, then commit the Kafka offset."""
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        security_protocol=security_protocol,
        group_id=consumer_group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        while not stop_signal.is_set():
            batches = await consumer.getmany(timeout_ms=1000, max_records=100)
            for records in batches.values():
                for record in records:
                    envelope = json.loads(record.value)
                    async with session_factory() as session:
                        await session.execute(
                            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                            {"tenant_id": envelope["tenant_id"]},
                        )
                        applied = await _apply_event(
                            session=session, envelope=envelope, consumer_name=consumer_group
                        )
                    logger.info(
                        "projection_consumer.event_processed",
                        event_id=envelope["event_id"],
                        event_type=envelope["event_type"],
                        applied=applied,
                    )
                await consumer.commit()
    finally:
        await consumer.stop()
