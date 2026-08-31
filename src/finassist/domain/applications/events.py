"""Domain events raised by the `Application` aggregate.

These are in-process domain events, not the Kafka envelope defined in master instruction §12 --
that envelope (event_id/schema_version/traceparent/etc.) is an infrastructure concern applied by
the outbox relay when it serializes one of these for publication (Phase 3). Domain code only
needs to know *that* something happened and *what* the relevant facts were.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from finassist.domain.applications.status import ApplicationStatus
from finassist.domain.shared.identifiers import ApplicationId, TenantId


@dataclass(frozen=True, slots=True)
class DomainEvent:
    application_id: ApplicationId
    tenant_id: TenantId
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ApplicationCreated(DomainEvent):
    product_id: str


@dataclass(frozen=True, slots=True)
class ApplicationStateChanged(DomainEvent):
    previous_status: ApplicationStatus
    new_status: ApplicationStatus
    reason: str
