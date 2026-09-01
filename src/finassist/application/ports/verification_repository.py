"""Port for persisting/reading one verification run's results (master instruction §10.1
`verification` schema: `verification_runs`, `verification_checks`, `contradictions`,
`external_response_snapshots`). One `add_run` call records all four, since a
`verify_application_facts` command always produces them together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.domain.verification.contradiction import SourceSystem, VerificationCheck


@dataclass(frozen=True, slots=True)
class ExternalResponseSnapshot:
    source_system: SourceSystem
    response_payload: dict[str, Any]


@runtime_checkable
class VerificationRepository(Protocol):
    async def add_run(
        self,
        *,
        run_id: str,
        tenant_id: TenantId,
        application_id: ApplicationId,
        checks: list[VerificationCheck],
        check_ids: list[str],
        snapshots: list[ExternalResponseSnapshot],
        snapshot_ids: list[str],
        completed_at: datetime,
    ) -> None:
        """Record one verification run, its checks (any `CONTRADICTED` verdict also lands in
        `contradictions`), and every raw external-system response captured along the way --
        including the two (bureau, core-banking) that never produce a verdict, kept for
        provenance/replay (master instruction §5.11)."""
        ...

    async def get_checks_for_application(
        self, *, tenant_id: TenantId, application_id: ApplicationId
    ) -> list[VerificationCheck]:
        ...
