# FinAssist — Agentic Loan Underwriting & Credit Decision Platform (synthetic/demo)

Built against `AGENTIC_LOAN_UNDERWRITING_MASTER_IMPLEMENTATION_INSTRUCTION.md`. Start with
[docs/architecture/phase-0-assessment.md](docs/architecture/phase-0-assessment.md) — it has the
repository assessment, confirmed scope/assumptions, target architecture, technology decision
matrix, phased plan, and Phase 0/1A acceptance criteria. Design decisions are recorded as ADRs in
[docs/adr/](docs/adr/).

**Status: Phase 0 (architecture baseline) and Phase 1A (production foundation) are implemented.**
Everything else in the master instruction (domain persistence, synthetic ecosystem, Temporal
workflows, document intelligence, policy/affordability engines, retrieval/agents, human review,
full observability, security hardening, Kubernetes/GitOps) is scoped to later phases per the plan
in the Phase 0 document — none of it is claimed as done. See that document for the phase-by-phase
mapping.

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
- `docker compose --profile core` for local API+worker.
- Lint/type/test/security/import-direction gates wired into a single `make ci` target
  (docs/adr/0004).

## Quickstart (Windows PowerShell or POSIX shell)

```bash
cp .env.example .env
uv sync --all-extras
make ci
make run-api      # http://localhost:8000/docs, /health/live, /health/ready, /metrics
make run-worker    # in a second terminal; http://localhost:8001/health/live
```

Or via Compose:

```bash
docker compose --profile core up --build
```

## Repository layout

See `docs/architecture/phase-0-assessment.md` §3/§5 for the full rationale. Top level:

- `src/finassist/` — application code (domain, application, infrastructure, ai, api, security,
  observability, bootstrap)
- `apps/` — process entrypoints (api, worker, web)
- `services/` — synthetic enterprise systems (mock LOS/KYC/bureau/employer/core-banking) — Phase 2
- `tests/` — unit, property, integration, contract, workflow, e2e, security, performance,
  evaluation
- `infra/` — compose, kubernetes, helm, opentofu, gitops, observability, keycloak, opa, openbao
- `docs/` — architecture, ADRs, API, threat model, runbooks, operations
