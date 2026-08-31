"""Maps `finassist.domain.applications.events.DomainEvent` subclasses to the
`(event_type, aggregate_type, payload)` triple stored in `outbox_events`/`audit_events`.

A new domain event type must be added here explicitly (the `else` branch raises) rather than
silently serializing an unknown shape -- an audit/outbox record with an undocumented payload
shape is worse than a loud failure at the point a new event type is introduced.
"""

from __future__ import annotations

from typing import Any

from finassist.domain.applications.events import (
    ApplicationCreated,
    ApplicationStateChanged,
    DocumentUploaded,
    DomainEvent,
)

AGGREGATE_TYPE_APPLICATION = "Application"


class UnmappedDomainEventError(TypeError):
    def __init__(self, event: DomainEvent) -> None:
        super().__init__(f"no outbox/audit mapping registered for {type(event).__name__}")


def event_to_record(event: DomainEvent) -> tuple[str, str, dict[str, Any]]:
    if isinstance(event, ApplicationCreated):
        return "ApplicationCreated", AGGREGATE_TYPE_APPLICATION, {"product_id": event.product_id}
    if isinstance(event, ApplicationStateChanged):
        return (
            "ApplicationStateChanged",
            AGGREGATE_TYPE_APPLICATION,
            {
                "previous_status": event.previous_status.value,
                "new_status": event.new_status.value,
                "reason": event.reason,
                "version": event.version,
            },
        )
    if isinstance(event, DocumentUploaded):
        return (
            "DocumentUploaded",
            AGGREGATE_TYPE_APPLICATION,
            {
                "document_id": event.document_id,
                "document_type": event.document_type,
                "object_key": event.object_key,
            },
        )
    raise UnmappedDomainEventError(event)
