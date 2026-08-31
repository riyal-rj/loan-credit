# Phase 1B Completion Report — Domain and Persistence Foundation

Status: **Accepted**
Date: 2026-08-31

## Scope delivered

Per docs/architecture/phase-0-assessment.md §5 and the master instruction's Phase 1B bullets:
domain value objects/aggregate/state machine for the `applications` bounded context, PostgreSQL
schema via Alembic migration, row-level-security tenant isolation, repositories, outbox/inbox/
idempotency implementation, and the audit event foundation (hash-chained, docs/adr/0009).

## What was built

- **Domain layer** (`src/finassist/domain/shared/`, `src/finassist/domain/applications/`):
  `Money` (decimal, currency-safe), typed `TenantId`/`ApplicantId`/`ApplicationId`/`ProductId`,
  `Clock`/`FixedClock`, the full 15-state `ApplicationStatus` machine with an exhaustively
  property-tested transition table, the `Application` aggregate (optimistic concurrency, domain
  events), `Applicant` and `Product` entities.
- **Application layer** (`src/finassist/application/`): `CreateApplicationCommand`/
  `SubmitApplicationCommand` handlers, `ApplicationRepository`/`ApplicantRepository`/
  `ProductCatalog`/`UnitOfWork` ports, `IdGenerator` port.
- **Infrastructure layer** (`src/finassist/infrastructure/postgres/`): SQLAlchemy 2.0 async ORM
  models, `SqlAlchemyUnitOfWork` (RLS session-variable setup, outbox write, hash-chained audit
  write, idempotency-key reservation via insert-and-catch-conflict), repository/product-catalog
  adapters.
- **Migration** (`migrations/versions/0001_initial_schema.py`): `identity.tenants`,
  `applications.{products,applicants,applications,application_versions,consent_records,
  state_transitions}`, `integration.{outbox_events,inbox_messages,idempotency_keys}`,
  `audit.{audit_events,audit_hashes}`; RLS + `FORCE ROW LEVEL SECURITY` + tenant-isolation policy
  on every tenant-scoped table; creates the `finassist_app` least-privilege role and grants; seeds
  a demo tenant/product.
- **Compose**: `postgres` (host port 5433 to avoid colliding with a developer's own Postgres),
  `migrate` (one-shot, runs as the superuser role), `api`/`worker` (updated to depend on
  `migrate` and connect as `finassist_app`).
- **Settings**: `database_url` (app role) vs `database_migration_url` (migration role) as two
  distinct, independently-validated settings; `/health/ready` gained a real Postgres connectivity
  check.

## Evidence

| Gate | Command | Result |
|---|---|---|
| Lint | `uv run ruff check src apps tests` | All checks passed |
| Types | `uv run mypy src apps` (strict) | Success: no issues found in 83 source files |
| Import direction | `uv run lint-imports` | 3 contracts kept, 0 broken |
| Unit + property tests | `make test` (`pytest`, no Docker) | 77 passed |
| Integration tests | `make test-integration` (real Postgres via testcontainers) | 6 passed |
| Combined coverage | `make coverage-check` | 95% (gate: 90%) |
| SAST | `uv run bandit -r src apps` | 0 findings |
| Dependency audit | `uv run pip-audit --skip-editable` | No known vulnerabilities |
| Container build + full stack | `docker compose --profile core up --build` | `migrate` exits 0, `api`/`worker` reach `Up (healthy)`, `/health/ready` reports both `secret_provider` and `postgres` healthy |

## Real bugs found and fixed during this phase

Each of these was caught by actually running the code against a real Postgres, not by review —
recorded here because the fixes are load-bearing, not incidental:

1. **RLS silently did not apply.** The local/testcontainers Postgres role is a bootstrap
   superuser; PostgreSQL exempts superusers from row-level security even with `FORCE ROW LEVEL
   SECURITY`. Fixed by introducing a second, non-superuser `finassist_app` role that the
   application connects as, with the superuser reserved for migrations only
   (`database_url` vs `database_migration_url`, docs/adr/0009). This is a security-relevant fix:
   without it, tenant isolation would have been a no-op in any environment where the app runs as
   the database owner/superuser.
2. **Timezone-naive vs timezone-aware datetime columns.** SQLAlchemy's default type-annotation
   mapping for `datetime.datetime` is a naive `DateTime()`, while the migration correctly created
   `TIMESTAMPTZ` columns -- asyncpg rejected tz-aware Python datetimes against the mismatched ORM
   type. Fixed via `Base.type_annotation_map = {datetime: DateTime(timezone=True)}`.
3. **Docker image builder/runtime path mismatch** (carried over from Phase 1A, hit again while
   adding `migrations`/`alembic.ini` to the image) -- already fixed in Phase 1A's completion, no
   regression here.
4. **`str(sqlalchemy.engine.URL)` masks the password** as `***` by default; a test helper that
   rebuilt a connection URL with new credentials via `str(url)` produced a URL with the literal
   string `***` as the password. Fixed by using `render_as_string(hide_password=False)`.
5. **Product reads needed to go through the same RLS-scoped transaction** as everything else.
   Originally `ProductCatalog` was a handler-level dependency wired independently of the
   `UnitOfWork`; moved it to `uow.products` so it shares the transaction's tenant context, which
   is also what let the RLS-on-products test (`test_rls_blocks_reading_another_tenants_product`)
   be written meaningfully at all.
6. **Coverage gate vs test isolation.** Running unit and integration tests in one `pytest`
   invocation let the integration suite's session-scoped environment-variable monkeypatching leak
   into unit tests of `Settings` validation. Fixed by splitting `testpaths` (bare `pytest`
   excludes `tests/integration`) and combining coverage explicitly across both invocations via
   `make ci-full` / `coverage-check`, rather than relying on pytest-cov's per-invocation
   `fail_under` auto-enforcement.

## Known limitations / accepted at this phase

- `applications.consent_records` and `integration.inbox_messages` are real tables (created by the
  migration, with RLS where applicable) but have no reader/writer code yet -- consent capture and
  the Kafka inbox consumer are Phase 3+ concerns (docs/adr/0009). This is a deliberate seam, not
  an oversight.
- The outbox table (`integration.outbox_events`) accumulates unpublished rows; there is no relay
  yet because Kafka doesn't exist until Phase 3. Expected and tracked, not a bug.
- `docs/adr/0009` notes that a DB-level `REVOKE UPDATE, DELETE` on `audit_events` (to make
  append-only enforcement DB-level, not just application-level) is deferred to Phase 9's security
  hardening alongside the rest of the privilege model.
- `make ci` (Docker-free) does not include the integration suite or the combined coverage gate;
  `make ci-full` does and requires Docker. Both are documented in the Makefile; a phase touching
  persistence should always be accepted against `ci-full`, not `ci` alone.

## Next phase

**Phase 2 — Synthetic enterprise ecosystem**: synthetic data generator and scenario catalog, mock
LOS/KYC/bureau/employer/core-banking services, contract schemas, deterministic fault injection,
document/object-storage lifecycle -- per docs/architecture/phase-0-assessment.md §5.
