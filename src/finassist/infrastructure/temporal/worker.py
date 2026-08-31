"""Builds the `temporalio.worker.Worker` that hosts `ApplicationWorkflow` and
`ApplicationActivities` (Phase 3). Connects its own dedicated `Client` -- separate from the one
`TemporalWorkflowRunner` holds, since only the API process starts/signals workflows, while only
the worker process needs to host and execute them.
"""

from __future__ import annotations

from temporalio.client import Client
from temporalio.worker import Worker

from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.bootstrap.settings import Settings
from finassist.domain.shared.clock import Clock
from finassist.infrastructure.temporal.activities import ApplicationActivities
from finassist.infrastructure.temporal.workflows import ApplicationWorkflow


async def build_worker(
    *, settings: Settings, uow_factory: UnitOfWorkFactory, clock: Clock
) -> Worker:
    client = await Client.connect(
        f"{settings.temporal_host}:{settings.temporal_port}",
        namespace=settings.temporal_namespace,
        tls=settings.temporal_tls_enabled,
    )
    activities = ApplicationActivities(uow_factory=uow_factory, clock=clock)
    return Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ApplicationWorkflow],
        activities=[
            activities.validate_intake_activity,
            activities.check_required_documents_activity,
            activities.apply_review_decision_activity,
        ],
    )
