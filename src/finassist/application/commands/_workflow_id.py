"""Shared workflow-ID derivation, used by every command that starts an `ApplicationWorkflow`
execution (docs/adr/0002: "one workflow execution maps to one application version").

A single function so the ID format only needs to be right in one place -- `submit_application`,
`resubmit_application`, and `finassist.infrastructure.temporal.client.TemporalWorkflowRunner`
(which only ever receives an already-computed ID, never recomputes one) all agree by construction.
"""

from __future__ import annotations

from finassist.domain.shared.identifiers import ApplicationId, TenantId


def application_workflow_id(
    *, tenant_id: TenantId, application_id: ApplicationId, version: int
) -> str:
    return f"application:{tenant_id}:{application_id}:v{version}"
