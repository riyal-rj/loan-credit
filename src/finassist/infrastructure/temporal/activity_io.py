"""Activity input/output dataclasses, split out from `activities.py` into their own
zero-heavy-dependency module.

`workflows.py` must import these (it needs the types to call activities and read results), but
must **not** import `activities.py` itself: `ApplicationActivities` transitively pulls in
SQLAlchemy, `uuid`/`random`-based ID generation, and the rest of the application/infrastructure
stack, and Temporal's workflow sandbox re-validates a workflow module's entire import graph under
restricted builtins at worker-start time -- pulling that graph into `workflows.py` fails
validation (``random.getrandbits restricted``) even though none of it ever executes inside the
workflow itself. Referencing activities by their registered string name
(`workflow.execute_activity`) instead of by class/method reference (`execute_activity_method`)
is what makes this split possible.
"""

from __future__ import annotations

from dataclasses import dataclass

VALIDATE_INTAKE_ACTIVITY = "validate_intake_activity"
CHECK_REQUIRED_DOCUMENTS_ACTIVITY = "check_required_documents_activity"
EXTRACT_DOCUMENT_FACTS_ACTIVITY = "extract_document_facts_activity"
VERIFY_FACTS_ACTIVITY = "verify_facts_activity"
ENTER_HUMAN_REVIEW_ACTIVITY = "enter_human_review_activity"
APPLY_REVIEW_DECISION_ACTIVITY = "apply_review_decision_activity"
"""Registered activity names -- the single source of truth `activities.py`'s `@activity.defn(name=
...)` decorators and `workflows.py`'s `workflow.execute_activity(<name>, ...)` calls both use, so
the two can never drift out of sync."""


@dataclass(frozen=True, slots=True)
class ActivityContext:
    """The workflow/activity IO boundary uses plain strings for IDs, not the typed
    `TenantId`/`ApplicationId` domain wrappers -- Temporal's default data converter serializes
    dataclasses field-by-field and typed ID reconstruction/validation happens once, inside the
    activity, matching how HTTP request models stay primitive-typed at the API boundary too."""

    tenant_id: str
    application_id: str


@dataclass(frozen=True, slots=True)
class ActivityStatusResult:
    status: str
    version: int


@dataclass(frozen=True, slots=True)
class ApplyReviewDecisionActivityInput:
    tenant_id: str
    application_id: str
    decision: str
    reason: str
    reviewer_id: str | None


@dataclass(frozen=True, slots=True)
class ExtractDocumentFactsActivityResult:
    document_count: int
    fact_count: int


@dataclass(frozen=True, slots=True)
class VerifyFactsActivityResult:
    contradiction_count: int
    summary: str


@dataclass(frozen=True, slots=True)
class EnterHumanReviewActivityInput:
    tenant_id: str
    application_id: str
    reason: str
