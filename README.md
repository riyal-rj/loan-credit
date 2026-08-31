# FinAssist — Agentic Loan Underwriting & Credit Decision Platform (synthetic/demo)

Built against `AGENTIC_LOAN_UNDERWRITING_MASTER_IMPLEMENTATION_INSTRUCTION.md`. Start with
[docs/architecture/phase-0-assessment.md](docs/architecture/phase-0-assessment.md) — it has the
repository assessment, confirmed scope/assumptions, target architecture, technology decision
matrix, phased plan, and Phase 0/1A acceptance criteria. Design decisions are recorded as ADRs in
[docs/adr/](docs/adr/).

**Status: Phase 0 (architecture baseline), Phase 1A (production foundation), and Phase 1B
(domain and persistence foundation) are implemented.** Everything else in the master instruction
(synthetic ecosystem, Temporal workflows, document intelligence, policy/affordability engines,
retrieval/agents, human review, full observability, security hardening, Kubernetes/GitOps) is
scoped to later phases per the plan in the Phase 0 document — none of it is claimed as done. See
[docs/architecture/phase-1b-completion.md](docs/architecture/phase-1b-completion.md) for what
Phase 1B added, the evidence it passed on, and the real bugs (RLS silently bypassed for
superusers, timezone-naive ORM columns, a password-masking bug in a test helper) it caught and
fixed along the way.

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

## Quickstart (Windows PowerShell or POSIX shell)

```bash
cp .env.example .env
uv sync --all-extras
make ci                # lint, types, import direction, unit+property tests, security scans
make migrate           # apply the Postgres schema (needs `docker compose up postgres` first)
make run-api           # http://localhost:8000/docs, /health/live, /health/ready, /metrics
make run-worker        # in a second terminal; http://localhost:8001/health/live
```

Or via Compose (brings up Postgres, runs the migration, then starts the API and worker):

```bash
docker compose --profile core up --build
```

Postgres is published on host port **5433** (not 5432) so it doesn't collide with a Postgres you
may already be running locally; see `.env.example`.

Integration tests need Docker (they spin up a disposable Postgres via testcontainers):

```bash
make test-integration   # or: make ci-full for the combined unit+integration+coverage gate
```

## Repository layout

See `docs/architecture/phase-0-assessment.md` §3/§5 for the full rationale. Top level:

- `src/finassist/` — application code (domain, application, infrastructure, ai, api, security,
  observability, bootstrap)
- `apps/` — process entrypoints (api, worker, web)
- `migrations/` — Alembic migrations (`versions/0001_initial_schema.py` is the Phase 1B schema)
- `services/` — synthetic enterprise systems (mock LOS/KYC/bureau/employer/core-banking) — Phase 2
- `tests/` — unit, property, integration (needs Docker), contract, workflow, e2e, security,
  performance, evaluation
- `infra/` — compose, kubernetes, helm, opentofu, gitops, observability, keycloak, opa, openbao
- `docs/` — architecture, ADRs, API, threat model, runbooks, operations
