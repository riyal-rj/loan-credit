# Phase 3 Completion Report — Durable Workflow and Intake

Status: **Accepted**
Date: 2026-08-31

## Scope delivered

Per the master instruction's Phase 3 bullets ("Durable workflow and intake") and
docs/architecture/phase-0-assessment.md §5:

- Temporal workflows/activities, signals, retries, versioning, replay tests
  (`src/finassist/infrastructure/temporal/`, `tests/workflow/`)
- Intake, submission, document upload, case status (`src/finassist/api/routes/applications.py` --
  the applications context's first HTTP routes; `create`/`submit` existed as untested-by-API
  command handlers since Phase 1B)
- Kafka events and projections (`src/finassist/infrastructure/kafka/`)
- Initial reviewer-queue creation (`review.review_queue_entries`, one internal decision endpoint)

Design rationale -- including a real design bug the already-accepted Phase 1B state machine caught
before this phase shipped it -- is recorded in docs/adr/0011.

## What was built

- **`ApplicationWorkflow`** (`infrastructure/temporal/workflows.py`): one execution per
  application version (ADR-0002), started by `submit`/`resubmit`, ended by a human decision or an
  SLA-timeout auto-escalation. Two automated activities (`validate_intake_activity`,
  `check_required_documents_activity`) always converge on `AWAITING_HUMAN_REVIEW` -- the accepted
  state machine has no automated path to `DECLINED`/`NEEDS_MORE_INFORMATION` (invariant §5.1) --
  followed by a signal/timeout wait and `apply_review_decision_activity`.
- **Activities** (`activities.py`) wrapping five new command handlers
  (`advance_intake_validation`, `advance_document_processing`, `apply_review_decision`, plus the
  shared `_enter_human_review` mutation and `upload_document`/`resubmit_application`), each
  idempotent via the existing `integration.idempotency_keys` mechanism keyed by Temporal's own
  `workflow_id:activity_id`.
- **`TemporalWorkflowRunner`** (`client.py`): the `WorkflowRunner` port's production adapter --
  idempotent workflow starts (`WorkflowIDReusePolicy.REJECT_DUPLICATE`), signal delivery.
  `Application.active_workflow_id` (new field) is how a signal finds the right running execution,
  since `version` keeps incrementing as the same execution progresses.
- **Kafka** (`infrastructure/kafka/`): `KafkaEventProducer`, an outbox relay
  (`outbox_relay.py`) that iterates `identity.tenants` and polls each tenant's own
  RLS-scoped session for unpublished `outbox_events`, and `KafkaProjectionConsumer`
  (`projection_consumer.py`) maintaining `applications.status_projection` with inbox-deduplicated
  redelivery handling (`integration.inbox_messages`'s first real consumer).
- **New API routes** (`api/routes/applications.py`): `POST /applications`,
  `POST /applications/{id}/submit`, `POST /applications/{id}/resubmit`,
  `POST /applications/{id}/documents`, `GET /applications/{id}`,
  `POST /internal/applications/{id}/review-decisions` (signals the workflow; does not mutate the
  aggregate directly). RFC 9457 mapping extended for seven domain exceptions that previously had
  no API surface to map from.
- **Database** (`migrations/versions/0002_phase3_workflow_and_review.py`): `applications.documents`,
  `applications.status_projection`, new `review` schema with `review_queue_entries`, and
  `applications.applications.active_workflow_id` -- all RLS-enabled like every other tenant-scoped
  table.
- **`apps/worker/main.py`** rewritten: the Phase 1A heartbeat loop is gone, replaced by three
  independently retry-with-backoff background tasks (Temporal worker, outbox relay, projection
  consumer) so a not-yet-reachable Temporal/Kafka at container startup degrades rather than
  crash-loops the process.
- **Compose**: `temporal` (dev-mode `server start-dev`, in-memory sqlite, Web UI on 8233) under a new
  `workflow` profile, `kafka` (KRaft, single broker) under a new `events` profile, both folded into
  `full`.
- **Settings**: `temporal_*`/`kafka_*` groups with local-dev defaults matching compose, plus
  production-safety validators (`temporal_tls_enabled`, `kafka_security_protocol != PLAINTEXT`)
  matching the existing pattern for every other dev-only adapter.

## Evidence

| Gate | Command | Result |
|---|---|---|
| Lint | `ruff check src apps tests services` | All checks passed |
| Types | `mypy src apps` (strict) | Clean across 109 source files |
| Import direction | `lint-imports` | 3 contracts kept, 0 broken (134 files, 389 dependencies) |
| Unit + property tests | `make test` | 133 passed |
| Workflow tests | `make test-workflow` (`temporalio.testing.WorkflowEnvironment`, no Docker) | 5 passed |
| Integration tests | `make test-integration` (real Postgres/MinIO/Kafka via testcontainers, plus a real local Temporal dev server) | 15 passed |
| Combined coverage | `make coverage-check` | 93% (gate: 90%) |
| SAST | `bandit -r src apps services` | 0 findings |
| Dependency audit | `pip-audit --skip-editable` | No known vulnerabilities |
| Full stack | `docker compose --profile full up --build` | postgres/minio/migrate/api/worker/5 mock services/temporal/kafka; `/health/ready` reports all four checks healthy (secret_provider, postgres, object_store, workflow_runner); manual smoke test: create → submit (workflow starts, visible in Temporal UI) → status shows `AWAITING_HUMAN_REVIEW` with a `review_queue_entries` row → `POST .../review-decisions` → final status `APPROVED`; a throwaway consumer against `finassist.applications.events` observed the published envelopes with `published_at` set in Postgres |

## Real bugs found and fixed during this phase

1. **The original design tried to reach `DECLINED`/`NEEDS_MORE_INFORMATION` automatically.**
   `validate_intake_activity` transitioning straight to `DECLINED` on an out-of-bounds request, and
   `check_required_documents_activity` straight to `NEEDS_MORE_INFORMATION` on zero documents, both
   failed at test time with `IllegalStateTransitionError` -- the already-accepted Phase 1B state
   machine only allows those outcomes *from* `AWAITING_HUMAN_REVIEW`/`ESCALATED`, which is master
   instruction invariant §5.1 enforced at the transition-legality level, not by convention. Fixed
   by having every automated stage escalate to human review with an explanatory reason instead
   (docs/adr/0011 decision 1) -- the type system caught a real "AI issuing the final decision"
   design bug before it shipped, not after.
2. **`ApplicationRepository.save()`'s optimistic-concurrency check assumes exactly one version
   bump per call.** Multi-hop command handlers (`advance_intake_validation`/
   `advance_document_processing`, which enter a stage then leave it in one `handle()`) that saved
   only once at the end raised spurious `ConcurrencyConflictError`s against their own fake
   backing store in the very first test run. Fixed by calling `save()` once per `transition_to`.
3. **`workflows.py` importing `ApplicationActivities` failed Temporal's workflow-sandbox
   validation** (`random.getrandbits restricted`) the first time a real `Worker` tried to load the
   workflow: `ApplicationActivities` transitively imports SQLAlchemy/`uuid`-based ID generation/the
   rest of the infrastructure stack, and the sandbox re-validates a workflow module's entire import
   graph under restricted builtins. Fixed by extracting the shared IO dataclasses and activity-name
   constants into a new dependency-free `activity_io.py`, and calling activities by registered name
   (`workflow.execute_activity("validate_intake_activity", ...)`) instead of importing the
   activities class.
4. **`aiokafka`/`temporalio` were not covered by the import-linter's forbidden-module list.** The
   contract already named `kafka`/`temporalio`, but this project's Kafka client is `aiokafka` (a
   different top-level import name) -- added explicitly so the contract protects against what the
   code actually imports, not what an earlier placeholder guessed it might.
5. **`bandit` flagged an `assert` used for post-`wait_condition` type narrowing** in the workflow
   (stripped under `python -O`, so not actually safety-critical, but also not the right pattern).
   Replaced with an explicit `if ... is None: raise RuntimeError(...)`, which is not stripped and
   gives mypy the same narrowing.

## Known limitations / accepted at this phase

- **Workflow start is best-effort, not outbox-guaranteed.** `submit`/`resubmit` persist
  `active_workflow_id` before attempting the (separate-system) Temporal start call; a failure there
  is logged loudly but does not fail the already-committed domain write. A reconciliation sweep for
  "committed but never started" is not built -- accepted gap for a later phase.
- **`governance.tool_calls`** (named in ADR-0002 alongside `integration.idempotency_keys`) is not
  created; Phase 3's deterministic activities are fully served by the existing idempotency-key
  mechanism. Deferred to Phase 6, where a bounded agent's tool-call audit trail actually needs it
  (docs/adr/0011 decision 4).
- **The reviewer queue and its one internal decision endpoint are a stopgap**, not Phase 7's real
  reviewer UI/API (assignment, claim, SLA dashboards, segregation of duties, master instruction
  §17). `ESCALATED` has no path back into an active workflow in this phase -- re-review after
  escalation is manual/ops-level until Phase 7.
- **`applications.status_projection` is not exposed via any API endpoint yet.** It exists to prove
  the outbox → Kafka → inbox-dedup → projection loop end to end (master instruction §12 "events and
  projections"); a case-list/dashboard endpoint reading it is future work.
- **Apicurio schema registry** (named in ADR-0003) is deferred; the Kafka envelope is a plain JSON
  object validated by code and tests, not a registry-enforced schema.
- **Temporal runs in dev mode** (`server start-dev`, in-memory sqlite, no TLS, no HA) --
  a persistent-store production cluster is Phase 9/10 scope, matching every other dev-only adapter
  in this codebase (Keycloak/OPA/OpenBao dev stubs, ADR-0005).
- **No document classification/extraction/OCR.** `check_required_documents_activity` only checks
  presence (`COUNT(*) >= 1`); real document intelligence is Phase 4.

## Next phase

**Phase 4 — Document intelligence and verification**: file safety, OCR/parsing, classification,
extraction, provenance; cross-source verification and contradiction model; reviewer evidence
rendering; extraction/verification evaluations -- per docs/architecture/phase-0-assessment.md §5.
The workflow's `check_required_documents_activity` step is exactly where Phase 4's real extraction
activities are inserted, without changing `ApplicationWorkflow`'s outer signal/timeout/decision
shape.
