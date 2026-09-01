"""Builds the `temporalio.worker.Worker` that hosts `ApplicationWorkflow` and
`ApplicationActivities` (Phase 3, extended Phase 4 with document intelligence/verification
dependencies). Connects its own dedicated `Client` -- separate from the one `TemporalWorkflowRunner`
holds, since only the API process starts/signals workflows, while only the worker process needs to
host and execute them.
"""

from __future__ import annotations

from temporalio.client import Client
from temporalio.worker import Worker

from finassist.application.ports.document_extractor import DocumentExtractor
from finassist.application.ports.document_parser import DocumentParser
from finassist.application.ports.external_verification import (
    BureauClient,
    CoreBankingClient,
    EmployerVerifier,
    KycVerifier,
)
from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.object_store import ObjectStore
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.bootstrap.settings import Settings
from finassist.domain.shared.clock import Clock
from finassist.infrastructure.temporal.activities import ApplicationActivities
from finassist.infrastructure.temporal.workflows import ApplicationWorkflow


async def build_worker(
    *,
    settings: Settings,
    uow_factory: UnitOfWorkFactory,
    clock: Clock,
    id_generator: IdGenerator,
    object_store: ObjectStore,
    document_parser: DocumentParser,
    document_extractor: DocumentExtractor,
    kyc_verifier: KycVerifier,
    employer_verifier: EmployerVerifier,
    bureau_client: BureauClient,
    core_banking_client: CoreBankingClient,
) -> Worker:
    client = await Client.connect(
        f"{settings.temporal_host}:{settings.temporal_port}",
        namespace=settings.temporal_namespace,
        tls=settings.temporal_tls_enabled,
    )
    activities = ApplicationActivities(
        uow_factory=uow_factory,
        clock=clock,
        id_generator=id_generator,
        object_store=object_store,
        document_parser=document_parser,
        document_extractor=document_extractor,
        kyc_verifier=kyc_verifier,
        employer_verifier=employer_verifier,
        bureau_client=bureau_client,
        core_banking_client=core_banking_client,
    )
    return Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ApplicationWorkflow],
        activities=[
            activities.validate_intake_activity,
            activities.check_required_documents_activity,
            activities.extract_document_facts_activity,
            activities.verify_facts_activity,
            activities.enter_human_review_activity,
            activities.apply_review_decision_activity,
        ],
    )
