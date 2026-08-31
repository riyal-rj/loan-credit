"""`TemporalWorkflowRunner`: the `WorkflowRunner` port's production adapter, backed by
`temporalio.client.Client`.

One `Client` per process, connected once by `ensure_ready()` (composition-root call, mirroring
`S3ObjectStore.ensure_ready`) and reused for every subsequent call -- unlike `S3ObjectStore`, a
Temporal `Client` wraps a long-lived gRPC channel that is meant to be held, not reopened per call.
"""

from __future__ import annotations

import contextlib

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from finassist.application.ports.workflow_runner import WorkflowRunner
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.infrastructure.temporal.workflows import (
    ApplicationWorkflow,
    ApplicationWorkflowInput,
    ReviewDecisionSignal,
)


class TemporalWorkflowRunner(WorkflowRunner):
    def __init__(
        self,
        *,
        target_host: str,
        namespace: str,
        task_queue: str,
        tls: bool,
        human_review_sla_seconds: float,
    ) -> None:
        self._target_host = target_host
        self._namespace = namespace
        self._task_queue = task_queue
        self._tls = tls
        self._human_review_sla_seconds = human_review_sla_seconds
        self._client: Client | None = None

    def _require_client(self) -> Client:
        if self._client is None:
            raise RuntimeError("TemporalWorkflowRunner used before ensure_ready() connected it")
        return self._client

    async def ensure_ready(self) -> None:
        self._client = await Client.connect(
            self._target_host, namespace=self._namespace, tls=self._tls
        )

    async def check_connectivity(self) -> None:
        client = self._require_client()
        # A cheap, side-effect-free RPC: exercises the real gRPC channel without mutating
        # anything. An empty result is a successful check; a disconnected channel raises on the
        # first page fetch, which `async for` triggers immediately.
        async for _ in client.list_workflows(page_size=1):
            break

    async def start_application_workflow(
        self,
        *,
        workflow_id: str,
        tenant_id: TenantId,
        application_id: ApplicationId,
        version: int,
        starting_status: str,
    ) -> None:
        client = self._require_client()
        workflow_input = ApplicationWorkflowInput(
            tenant_id=str(tenant_id),
            application_id=str(application_id),
            version=version,
            starting_status=starting_status,
            human_review_sla_seconds=self._human_review_sla_seconds,
        )
        # Someone already started (or ran to completion) this exact workflow_id -- since IDs are
        # deterministic per application version, that means a retried/duplicate start call, not a
        # conflicting one. Treat as a successful idempotent no-op.
        with contextlib.suppress(WorkflowAlreadyStartedError):
            await client.start_workflow(
                ApplicationWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )

    async def signal_review_decision(
        self, *, workflow_id: str, decision: str, reason: str, reviewer_id: str
    ) -> None:
        client = self._require_client()
        handle = client.get_workflow_handle_for(ApplicationWorkflow.run, workflow_id=workflow_id)
        await handle.signal(
            ApplicationWorkflow.submit_review_decision,
            ReviewDecisionSignal(decision=decision, reason=reason, reviewer_id=reviewer_id),
        )
