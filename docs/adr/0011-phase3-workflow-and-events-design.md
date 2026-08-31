# ADR-0011: Phase 3 workflow, event-streaming, document-upload, and reviewer-queue design

## Status
Accepted

## Context
Phase 3 (master instruction §25, "Durable workflow and intake") needed Temporal workflows/
activities/signals/retries/versioning/replay tests; intake, submission, document upload, case
status; Kafka events and projections; initial reviewer queue creation. ADR-0002 already committed
to Temporal as the macro-orchestrator and the shape of activity idempotency; this ADR records the
concrete implementation decisions ADR-0002 left open, plus several corrections discovered only by
running the code -- one of them a genuine design bug in the original plan, caught by the existing,
already-accepted Phase 1B state machine rejecting an illegal transition.

## Decisions

**1. No automated stage may reach `DECLINED` or `NEEDS_MORE_INFORMATION`; every one of them
escalates to `AWAITING_HUMAN_REVIEW` instead, with a reason explaining why.** The original design
for this phase had `validate_intake_activity` transition straight to `DECLINED` on an out-of-bounds
request, and `check_required_documents_activity` transition straight to `NEEDS_MORE_INFORMATION`
on zero uploaded documents. Both failed at test time with `IllegalStateTransitionError`: the
Phase 1B state machine (`domain.applications.status`, exhaustively property-tested and already
accepted) only allows `DECLINED`/`APPROVED`/`NEEDS_MORE_INFORMATION`/`ESCALATED` to be reached
*from* `AWAITING_HUMAN_REVIEW` or `ESCALATED` -- never automatically. That is master instruction
invariant §5.1 ("no final credit decision without an authenticated, authorized human action")
enforced at the transition-legality level, not merely by convention, and the original design would
have violated it had the type system not caught it first. The fix
(`application/commands/_enter_human_review.py`) is a shared mutation every automated stage that
would otherwise reject/request-more-info calls instead: transition to `AWAITING_HUMAN_REVIEW`,
create a reviewer-queue entry, record why. `POLICY_EVALUATION`/`AFFORDABILITY_EVALUATION`/
`FRAUD_ANALYSIS`/`RISK_SYNTHESIS` are skipped entirely for the same reason ADR-0002 anticipated: no
automated engine for them exists yet (Phase 5/6), so a passing document check escalates too, via
the same shared path, with a reason saying so.

**2. Consequently, `ApplicationWorkflow` has exactly two automated activities before the human
decision, not three.** `validate_intake_activity` and `check_required_documents_activity` both
*always* end at `AWAITING_HUMAN_REVIEW` (decision #1), so there is nothing left for a separate
"enter human review" activity to do that the other two don't already do themselves. The workflow
skips `check_required_documents_activity` entirely when intake validation already escalated
(status is no longer `DOCUMENT_PROCESSING`, so the transition would be illegal a second time).

**3. Activities reference each other and the workflow's `apply_review_decision_activity` by
registered *name* (`workflow.execute_activity("validate_intake_activity", ...)`), never by
importing `ApplicationActivities` and using `execute_activity_method`.** `ApplicationActivities`
transitively imports SQLAlchemy, `uuid`/`random`-based ID generation, and the rest of the
application/infrastructure stack; Temporal's workflow sandbox re-validates a workflow module's
*entire* import graph under restricted builtins at worker-start time, and pulling that graph into
`workflows.py` failed validation (`random.getrandbits restricted`) even though none of it ever
executes inside the workflow. `activity_io.py` -- plain IO dataclasses and the three activity-name
constants, zero heavy imports -- is the only module `workflows.py` and `activities.py` both
import, so the two can't drift out of sync without also being safe for the sandbox. Caught by
actually running a worker against the workflow, not by review.

**4. Activity idempotency reuses the existing `integration.idempotency_keys` mechanism, keyed by
Temporal's own `f"{workflow_id}:{activity_id}"`, instead of a new `governance.tool_calls` table.**
ADR-0002 names both as *where* an operation key can land; `governance.tool_calls` is deferred to
Phase 6, where it is actually needed (a bounded agent's tool-call audit trail) -- introducing it
now would be a second mechanism doing the same job as one that already exists.  `activity_id` alone
is not unique across different workflow executions (Temporal assigns small incrementing per-run
IDs), so it is always combined with `workflow_id`, which already encodes tenant/application/
version.

**5. `Application.active_workflow_id` is a new plain bookkeeping field on the aggregate, not
derived from `version`.** A running workflow's activities keep incrementing `version` as they drive
the case forward, so `version` cannot be used to reconstruct which workflow execution a signal must
target. `submit`/`resubmit` compute a deterministic workflow ID
(`application:{tenant}:{application}:v{version}`) and call `Application.attach_workflow` *before*
`save()`, so the ID is durable before the best-effort call that actually starts the workflow;
`apply_review_decision_activity` clears it (`detach_workflow`) once a decision lands, since that
workflow execution is ending either way.

**6. Multi-hop command handlers call `save()` once per `transition_to`, not once per `handle()`.**
`ApplicationRepository.save()`'s optimistic-concurrency check assumes exactly one version
increment since the caller's load (`expected_prior_version = application.version - 1`), true for
every single-transition Phase 1B/2 handler. `advance_intake_validation`/
`advance_document_processing` make two `transition_to` calls in one handler invocation (entering a
stage, then leaving it), so each needs its own `save()` -- confirmed as a real `ConcurrencyConflict
Error` when a first draft of this phase saved only once. This also means the audit trail
(`application_versions`) gets one immutable snapshot per intermediate stage instead of skipping
straight to the final one, which is a better fit for docs/adr/0009's replay guarantee anyway.

**7. The reviewer queue (`review.review_queue_entries`) and its one internal decision endpoint
(`POST /internal/applications/{id}/review-decisions`) are a Phase-3 stopgap, not Phase 7's real
reviewer UI/API.** Assignment, claim, SLA dashboards, segregation of duties (master instruction
§17) are out of scope here; this is one table plus enough wiring to signal a running workflow end
to end. The endpoint only *signals*; it never mutates the `Application` aggregate directly --
`apply_review_decision_activity`, running inside the workflow, does that -- keeping Temporal the
sole authority over when a decision is actually applied (ADR-0002).

**8. The outbox relay reads across tenants by iterating `identity.tenants` and setting `app.
tenant_id` per tenant, never via a superuser/BYPASSRLS connection.** `identity.tenants` is the one
table with no RLS policy, so it is the only safe source of "which tenants exist" for a
cross-tenant background process. Each sweep opens a short-lived session per tenant, `SET LOCAL app.
tenant_id`, and polls that tenant's `outbox_events WHERE published_at IS NULL ... FOR UPDATE SKIP
LOCKED` -- the exact mechanism `SqlAlchemyUnitOfWork` already uses for request-scoped writes,
applied to a background sweep instead. The bounded-backlog check ADR-0009 flagged for this phase
(`unpublished_backlog_size`) has to iterate the same way, for the same reason: a session with no
`app.tenant_id` set matches zero rows under `FORCE ROW LEVEL SECURITY`, which would silently
under-report "no backlog" rather than raising.

**9. `applications.status_projection`, maintained by `KafkaProjectionConsumer`, is the first real
consumer of `integration.inbox_messages`.** Master instruction §12 asks for "Kafka events *and
projections*"; the projection consumer closes the outbox -> Kafka -> inbox-dedup -> read-model loop
end to end, using the same insert-and-catch-conflict dedup shape `reserve_idempotency_key` already
uses. It is deliberately not exposed via API yet -- `GET /applications/{id}` reads the
strongly-consistent authoritative `applications` table directly, not the eventually-consistent
projection -- and is documented as backing a future case-list/dashboard endpoint.

**10. Local dev infrastructure stays dev-only, matching ADR-0005's pattern.** Temporal:
`temporalio/temporal`'s `server start-dev` (single binary, in-memory sqlite, no TLS, built-in Web
UI on 8233) -- workflow history does not survive a container restart, deliberately, to avoid
fighting the image's non-root user over a bind-mounted directory's write permissions for something
that's ephemeral by design anyway. Kafka: `apache/kafka` (official image), single broker, KRaft
mode, no ZooKeeper.
Apicurio schema registry (named in ADR-0003) is deferred past this phase -- the JSON envelope is
validated by code and tests, not a registry. A persistent-store Temporal cluster and a schema
registry are Phase 9/10 concerns. `Settings._validate_production_constraints` rejects
`environment=production` unless `temporal_tls_enabled=true` and `kafka_security_protocol != PLAINTEXT`,
so the dev-mode adapters can't silently reach production the way `SecretProviderKind.ENV` already
can't (ADR-0005).

**11. `apps/worker/main.py`'s three background tasks (Temporal worker, outbox relay, projection
consumer) each retry-with-backoff independently rather than crash-looping the process.**
`docker compose`'s `depends_on: service_healthy` ordering is a best effort, not a guarantee, and
`core`/`full` profiles no longer guarantee Temporal/Kafka are even included (`workflow`/`events`
profiles) -- so a worker that fails to start because a dependency wasn't reachable in the first
few seconds is exactly the "must not crash-loop on a slow/unavailable dependency" failure
`api/app.py`'s `object_store.ensure_ready()` handling already avoids for the API process, now
applied uniformly to all three of the worker's jobs.

## Consequences
- The state machine remains the single source of truth for legal transitions; nothing in Phase 3
  (or any future phase) can special-case its way to an automated adverse decision, because the
  type-level check refuses it before a test even has to catch it.
- Every application that reaches `AWAITING_HUMAN_REVIEW` has an explicit, human-readable reason on
  the transition itself (out-of-bounds request, no documents, or "no automated engine yet") --
  useful now for manual review, and directly reusable as Phase 5/6's real reason-code surface once
  automated policy/affordability/fraud/risk exists.
- Adding Phase 5/6's real automated stages later is additive: they become new activities inserted
  between `check_required_documents_activity` and the (now-conditional) escalation, without
  changing the workflow's outer signal/timeout/decision shape.
- The worker process now genuinely depends on Temporal and Kafka to do useful work; a `--profile
  core` compose run stays live (liveness passes) but does not process cases until `workflow`/
  `events`/`full` bring the real dependencies up -- called out explicitly in `compose.yaml`'s
  header comment rather than left implicit.

## Alternatives considered
- **A `governance.tool_calls` table now, per ADR-0002's literal wording** -- rejected for this
  phase: no agent tool call exists yet to audit (Phase 6), and the existing idempotency-key table
  already satisfies the "stable operation key" requirement for deterministic activities.
- **Importing `ApplicationActivities` into `workflows.py` and using `workflow.unsafe.
  imports_passed_through()` for its entire transitive dependency tree** -- rejected: that context
  manager exists for genuinely side-effect-free third-party imports (e.g. this project's own use
  for `ApplicationStatus`), not for a module that imports SQLAlchemy/aioboto3/asyncpg; passing all
  of that through would silence the sandbox's actual job of catching non-determinism, not just the
  false positive.
- **A single "advance and escalate" mega-activity instead of two plus a shared mutation helper** --
  rejected: `validate_intake_activity` and `check_required_documents_activity` are independently
  idempotent, independently retryable, and independently meaningful audit-trail entries; merging
  them would lose that without actually reducing complexity, since the shared escalation logic
  still has to exist somewhere.
- **Auto-escalating to `ESCALATED` on SLA timeout by polling instead of a durable timer** --
  rejected by ADR-0002 already ("durable timers for review SLA ... not polling loops"); the Phase 3
  implementation uses `workflow.wait_condition(..., timeout=...)`, verified against
  `temporalio.testing.WorkflowEnvironment`'s time-skipping test server so the test suite doesn't
  need to wait a real day for a real SLA to elapse.
