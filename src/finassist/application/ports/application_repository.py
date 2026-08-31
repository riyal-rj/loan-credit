"""Port for persisting and retrieving `Application` aggregates.

Deliberately narrow: `get`/`add`/`save` only. No generic `find_by(**kwargs)` or query-building
escape hatch -- a new lookup need gets a new, explicitly named method (and, if it crosses
aggregates, a query object under `application/queries/`), never a leaky filter API that could
accidentally omit tenant scoping.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from finassist.domain.applications.application import Application
from finassist.domain.shared.identifiers import ApplicationId, TenantId


@runtime_checkable
class ApplicationRepository(Protocol):
    async def get(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> Application | None:
        """Return the application, or `None` if it does not exist for this tenant.

        Never returns another tenant's row -- enforced by RLS at the database layer
        (docs/adr/0009), not by a filter clause here that could be forgotten.
        """
        ...

    async def add(self, application: Application) -> None:
        """Persist a brand-new aggregate. Raises if `application_id` already exists."""
        ...

    async def save(self, application: Application) -> None:
        """Persist changes to an existing aggregate using optimistic concurrency.

        Raises `finassist.domain.applications.exceptions.ConcurrencyConflictError` if the
        persisted version does not match the version this aggregate was loaded at.
        """
        ...
