# FinAssist — Agentic Loan Underwriting & Credit Decision Platform (synthetic/demo)

Built against `AGENTIC_LOAN_UNDERWRITING_MASTER_IMPLEMENTATION_INSTRUCTION.md`. Start with
[docs/architecture/phase-0-assessment.md](docs/architecture/phase-0-assessment.md) — it has the
repository assessment, confirmed scope/assumptions, target architecture, technology decision
matrix, phased plan, and Phase 0/1A acceptance criteria. Design decisions are recorded as ADRs in
[docs/adr/](docs/adr/).

**Status: Phase 0 (architecture baseline), Phase 1A (production foundation), Phase 1B (domain and
persistence foundation), Phase 2 (synthetic enterprise ecosystem), Phase 3 (durable workflow and
intake), and Phase 4 (document intelligence and verification) are implemented.** Everything else in
the master instruction (policy/affordability engines, retrieval/agents, full human review, full
observability, security hardening, Kubernetes/GitOps) is scoped to later phases per the plan in the
Phase 0 document — none of it is claimed as done. See
[docs/architecture/phase-1b-completion.md](docs/architecture/phase-1b-completion.md),
[docs/architecture/phase-2-completion.md](docs/architecture/phase-2-completion.md),
[docs/architecture/phase-3-completion.md](docs/architecture/phase-3-completion.md), and
[docs/architecture/phase-4-completion.md](docs/architecture/phase-4-completion.md) for what each
phase added, the evidence it passed on, and the real bugs each one caught and fixed along the way
(RLS silently bypassed for superusers, timezone-naive ORM columns, a non-deterministic generator,
an object-store startup path that could crash-loop the API, botocore's default timeouts turning an
unreachable dependency into an 80-second hang, an original Phase 3 design that tried to reach
`DECLINED`/`NEEDS_MORE_INFORMATION` automatically and was rejected by the already-accepted state
machine, a Temporal workflow-sandbox import-graph failure, 37 CVEs in the originally pinned `pypdf`
version, an Alembic revision ID that silently truncated past its 32-character column limit, and a
SQLAlchemy/asyncpg insert-batching order bug that violated a real foreign key on real Postgres).

## What exists right now

- A modular-monolith package skeleton (`src/finassist/`) with enforced dependency direction
  (domain → nothing framework-specific; application → ports; infrastructure → implements ports;
  api/worker → composition root).
- Validated, fail-fast configuration (`finassist.bootstrap.settings`).
- Structured JSON logging with correlation-ID and trace-ID injection and centralized redaction
  (`finassist.bootstrap.logging`).
- OpenTelemetry tracing bootstrap + FastAPI auto-instrumentation
  (`finassist.bootstrap.telemetry`).
- Prometheus metrics (`finassist.observability.metrics`) exposed at `/metrics`.
- RFC 9457 problem-details error handling for the whole API.
- `SecretProvider`/`AuthenticationProvider`/`AuthorizationProvider` ports with dev-only
  implementations, structurally prevented from running under `environment=production`
  (docs/adr/0005).
- An API process (`apps/api/main.py`) with `/health/live`, `/health/ready` (extensible dependency
  check registry), `/metrics`, and a request-size-limit + metrics + correlation-ID middleware
  chain.
- A worker process (`apps/worker/main.py`) with its own liveness endpoint, heartbeat loop, and
  graceful shutdown — Temporal wiring lands in Phase 3.
- A non-root, multi-stage, read-only-root-filesystem container image for each process.
- `docker compose --profile core` for local API + worker + PostgreSQL + a one-shot migration job.
- Lint/type/test/security/import-direction gates wired into a single `make ci` target
  (docs/adr/0004); `make ci-full` adds the Docker-dependent integration suite and the combined
  coverage gate (docs/architecture/phase-1b-completion.md).
- The `applications` bounded context end to end: domain aggregate + 15-state machine
  (`finassist.domain.applications`), command handlers for create/submit
  (`finassist.application.commands`), a PostgreSQL schema with row-level-security tenant
  isolation, an outbox + hash-chained append-only audit log, and idempotency-key-protected
  commands (`finassist.infrastructure.postgres`, `migrations/versions/0001_initial_schema.py`,
  docs/adr/0009).
- A synthetic enterprise ecosystem (`services/`): a deterministic, scenario-driven data generator
  and a 10-scenario catalog (`services/synthetic_data`), five mock external services -- LOS, KYC,
  bureau, employer, core-banking -- with header-selected scenarios and fault injection
  (`services/mock-*`, docs/adr/0010), and a real, tenant-isolated, versioned object-storage
  document lifecycle (`finassist.application.ports.object_store`,
  `finassist.infrastructure.object_store`, MinIO).
- Durable case orchestration (`finassist.infrastructure.temporal`): an `ApplicationWorkflow`
  driving intake validation, document-presence checking, and human-review escalation through
  Temporal activities, signals (`submit_review_decision`), and a durable SLA timer -- every
  automated stage escalates to a human rather than auto-declining/auto-requesting-more-information,
  since the accepted state machine only allows those outcomes from human review
  (docs/adr/0002, docs/adr/0011).
- Real HTTP routes for the `applications` context for the first time
  (`finassist.api.routes.applications`): create, submit, resubmit, document upload (into the
  Phase-2 object store), case status, and an internal reviewer-decision endpoint that signals the
  running workflow.
- Kafka event streaming (`finassist.infrastructure.kafka`): an outbox relay that publishes
  `integration.outbox_events` per tenant (RLS-respecting, never a superuser connection) to
  `finassist.applications.events`, and a projection consumer that maintains `applications.
  status_projection` with inbox-deduplicated redelivery handling.
- Document intelligence and verification (`finassist.domain.documents`,
  `finassist.domain.verification`, `finassist.infrastructure.documents`,
  `finassist.infrastructure.external_systems`): file-safety scanning, real PDF text extraction
  (`pypdf`), deterministic fact extraction with full provenance against the Phase 2 synthetic
  document corpus, and cross-source verification against the mock KYC/bureau/employer/
  core-banking services over real HTTP -- wired into `ApplicationWorkflow` between the
  document-presence check and human-review escalation, and exposed via `GET
  /applications/{id}/evidence` (docs/adr/0012).

## Quickstart (Windows PowerShell or POSIX shell)

```bash
cp .env.example .env
uv sync --all-extras
make ci                # lint, types, import direction, unit+property tests, security scans
make migrate           # apply the Postgres schema (needs `docker compose up postgres` first)
make run-api           # http://localhost:8000/docs, /health/live, /health/ready, /metrics
make run-worker        # in a second terminal; http://localhost:8001/health/live
```

Or via Compose (brings up Postgres + MinIO, runs the migration, then starts the API and worker):

```bash
docker compose --profile core up --build
```

Add the synthetic mock services (LOS/KYC/bureau/employer/core-banking) with `synthetic-systems`,
Temporal with `workflow`, and Kafka with `events` -- or bring up everything at once with `full`:

```bash
docker compose --profile full up --build
```

`core` alone still boots (liveness passes), but the worker's three background jobs (Temporal
worker, outbox relay, projection consumer) each retry-with-backoff until Temporal/Kafka are
actually reachable -- cases won't move past `SUBMITTED` without `workflow`/`events`/`full`
(docs/adr/0011).

Postgres is published on host port **5433** (not 5432) so it doesn't collide with a Postgres you
may already be running locally; see `.env.example`. MinIO uses its own defaults (9000 API / 9001
console), the mock services listen on 9101-9105, Temporal's frontend is on **7233** (Web UI on
**8233**), and Kafka's host-visible listener is on **9094**.

Integration tests need Docker (they spin up disposable Postgres, MinIO, and Kafka containers via
testcontainers, plus a real local Temporal dev server the SDK manages itself):

```bash
make test-integration   # or: make ci-full for the combined unit+integration+coverage gate
```

Temporal workflow tests (control-flow/replay, against `temporalio.testing.WorkflowEnvironment`'s
time-skipping test server -- no Docker needed) run separately:

```bash
make test-workflow
```

Contract tests for the mock services don't need Docker (they run the FastAPI apps in-process):

```bash
uv run pytest tests/contract
```

## Repository layout

See `docs/architecture/phase-0-assessment.md` §3/§5 for the full rationale. Top level:

- `src/finassist/` — application code (domain, application, infrastructure, ai, api, security,
  observability, bootstrap); `infrastructure/temporal` (workflow/activities/client/worker) and
  `infrastructure/kafka` (outbox relay/projection consumer) are Phase 3
- `apps/` — process entrypoints (api, worker, web)
- `migrations/` — Alembic migrations (`versions/0001_initial_schema.py` is the Phase 1B schema)
- `services/` — synthetic enterprise systems: `synthetic_data` (generator/scenario catalog),
  `common` (shared scenario/fault-injection plumbing), `mock-*` (LOS/KYC/bureau/employer/
  core-banking FastAPI apps) — Phase 2
- `tests/` — unit, property, integration (needs Docker), contract (mock services, no Docker),
  workflow, e2e, security, performance, evaluation
- `infra/` — compose, kubernetes, helm, opentofu, gitops, observability, keycloak, opa, openbao
- `docs/` — architecture, ADRs, API, threat model, runbooks, operations
