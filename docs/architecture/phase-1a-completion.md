# Phase 1A Completion Report — Production Foundation

Status: **Accepted**
Date: 2026-08-31

## Scope delivered

Per docs/architecture/phase-0-assessment.md §5/§6: project structure, validated fail-fast
configuration, structured logging, OpenTelemetry bootstrap, health/readiness/metrics endpoints,
security-safe configuration with secret/auth ports, lint/type/test/security tooling, minimal API
and worker boot paths, and Compose/CI foundation.

## Evidence

| Gate | Command | Result |
|---|---|---|
| Lint | `uv run ruff check src apps tests` | All checks passed |
| Types | `uv run mypy src apps` (strict) | Success: no issues found in 59 source files |
| Import direction | `uv run lint-imports` | 3 contracts kept, 0 broken |
| Tests | `uv run pytest` | 29 passed, 94.29% branch coverage (gate: 90%) |
| SAST | `uv run bandit -r src apps` | 0 findings |
| Dependency audit | `uv run pip-audit --skip-editable` | No known vulnerabilities |
| Runtime smoke (API) | `uv run uvicorn apps.api.main:app` + curl | `/health/live`→200, `/health/ready`→200 (secret_provider check healthy), `/metrics`→200 with `finassist_http_requests_total` present |
| Runtime smoke (worker) | `uv run python -m apps.worker.main` | Boots, logs `worker.startup.complete`, heartbeat fires, own `/health/live`→200, structured JSON/console logs and OTel spans confirmed end-to-end (uvicorn's own logger output is captured through the same structlog pipeline) |

Dependency versions were bumped during this phase specifically because `pip-audit` found real,
currently-known CVEs in the initially-pinned `starlette` (pulled transitively by an older FastAPI
pin) and `pytest`; both were upgraded to patched major versions (FastAPI 0.141.x / Starlette
1.6.x / pytest 9.1.x / pytest-asyncio 1.4.x) and the full gate was re-run clean afterward.

## Known limitations / accepted at this phase

- **Docker image build/run was not verified in this session** — Docker Desktop was not running
  in this environment and did not come up after being launched (waited ~2 minutes). The
  `Dockerfile`/`Dockerfile.worker`/`compose.yaml` are written and reviewed but not yet proven by
  an actual build. **Action for the user:** once Docker Desktop is running, run
  `docker compose --profile core up --build` and confirm both healthchecks go green; report back
  if the build fails so it can be fixed before Phase 1B.
- One accepted, tracked warning: Starlette 1.6.0's `TestClient` emits a
  `StarletteDeprecationWarning` recommending an `httpx2` package as an `httpx` replacement for
  `starlette.testclient`. `httpx2` is not yet an established, widely-adopted release as of this
  build; not acted on now, revisit when Starlette's migration path stabilizes.
- Readiness currently has exactly one real dependency check (`secret_provider`), because no
  database/cache/broker integration exists yet — this is correct for Phase 1A's actual scope, not
  a shortcut; the `ReadinessCheck` registry in `finassist.api.routes.health` is built specifically
  so Phase 1B can add a PostgreSQL check by appending to `READINESS_CHECKS`, no endpoint changes.
- `make` is not installed in the primary Windows dev shell used for this session; every
  `Makefile` target was verified by running its underlying `uv run ...` command directly instead.
  The Makefile itself is unchanged in behavior; users with `make` available (WSL, Git Bash with
  make, CI runners) can use it directly.
- Coverage gate is 90% branch coverage repo-wide per `pyproject.toml`; the master instruction's
  95% bar for "risk-critical" modules (policy, affordability, decision, authorization,
  idempotency, audit) applies starting Phase 1B/5 once those modules exist — tracked, not yet
  enforced separately, since there is no risk-critical code yet to hold to that bar.

## Next phase

**Phase 1B — Domain and persistence foundation**: domain value objects/aggregates/state machine
for the `applications` bounded context, PostgreSQL schema + Alembic migrations + row-level-security
tenant isolation, repositories, outbox/inbox/idempotency implementation, and the audit event
foundation — per docs/architecture/phase-0-assessment.md §5.
