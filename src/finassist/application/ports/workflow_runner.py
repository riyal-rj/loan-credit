"""Port for starting/signaling the durable Temporal workflow that orchestrates an application
version (docs/adr/0002, docs/adr/0011).

Mirrors `object_store.py`'s shape: `ensure_ready`/`check_connectivity` for startup/`/health/ready`
wiring, narrow explicit methods instead of a generic "send any signal" escape hatch. Command
handlers depend on this port, never on `temporalio` directly (enforced by the import-linter
contract forbidding `temporalio` in `finassist.application`).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from finassist.domain.shared.identifiers import ApplicationId, TenantId


@runtime_checkable
class WorkflowRunner(Protocol):
    async def ensure_ready(self) -> None: ...

    async def check_connectivity(self) -> None: ...

    async def start_application_workflow(
        self,
        *,
        workflow_id: str,
        tenant_id: TenantId,
        application_id: ApplicationId,
        version: int,
        starting_status: str,
    ) -> None:
        """Start the `ApplicationWorkflow` execution identified by ``workflow_id``.

        ``workflow_id`` is computed by the caller (a command handler) and persisted on the
        aggregate (`Application.attach_workflow`) *before* this is called, so a failure here is
        recoverable: the ID is already durable and starting a workflow with the same ID twice is
        a no-op restart, not a duplicate (Temporal's default `WorkflowIDReusePolicy` rejects a
        second start against a still-running execution with that ID).
        """
        ...

    async def signal_review_decision(
        self,
        *,
        workflow_id: str,
        decision: str,
        reason: str,
        reviewer_id: str,
    ) -> None:
        """Send the `submit_review_decision` signal to the running workflow ``workflow_id``.

        The workflow's own activity (not this call) is what applies the decision to the
        `Application` aggregate -- signaling only wakes the workflow's `wait_condition` (ADR-0002:
        "human waits ... are Temporal signals ... never polling loops").
        """
        ...
