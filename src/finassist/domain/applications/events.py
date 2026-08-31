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
    version: int
    """The aggregate's version *after* this transition (Phase 3): carried so a downstream
    consumer -- e.g. `KafkaProjectionConsumer` -- can maintain an ordered read model without a
    second query back to the aggregate."""


@dataclass(frozen=True, slots=True)
class DocumentUploaded(DomainEvent):
    """Raised by `UploadDocumentHandler` (Phase 3) -- not produced by an `Application.
    transition_to` call, since uploading a document is not itself a case-status change. The
    handler constructs this event directly and passes it to `UnitOfWork.record_domain_events`."""

    document_id: str
    document_type: str
    object_key: str
