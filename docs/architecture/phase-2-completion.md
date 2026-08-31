# Phase 2 Completion Report — Synthetic Enterprise Ecosystem

Status: **Accepted**
Date: 2026-08-31

## Scope delivered

Per the master instruction's Phase 2 bullets and docs/architecture/phase-0-assessment.md §5:

- Synthetic data generator and scenario catalog (`services/synthetic_data/`)
- Mock LOS, KYC, bureau, employer, and core-banking services with deterministic scenario
  behavior and fault injection (`services/mock-*`)
- Contract schemas and contract tests (`tests/contract/`)
- Document/object-storage lifecycle: a real, production `ObjectStore` port/adapter
  (`src/finassist/application/ports/object_store.py`,
  `src/finassist/infrastructure/object_store/minio_client.py`) plus synthetic PDF document
  generation to exercise it end-to-end

Design rationale for the choices this phase made (hyphenated single-file mock services, header-
based scenario selection, key-prefix tenant isolation for object storage, explicit timeouts) is in
docs/adr/0010.

## What was built

- **`services/synthetic_data/`**: deterministic seeding (`rng.py`), a 10-entry scenario catalog
  covering both data scenarios (thin-file bureau, KYC identity mismatch, employer mismatch,
  duplicate identity, low-balance/NSF) and fault scenarios (timeout, server error, malformed
  response, rate limit), generators for applicants/bureau/KYC/employer/transactions, and a
  hand-rolled minimal-but-valid PDF writer for synthetic pay-stub/ID documents.
- **`services/common/`**: shared `X-Synthetic-Scenario` header resolution and fault-injection
  dependency every mock service uses instead of reimplementing it.
- **Five mock services** (`services/mock-kyc`, `mock-bureau`, `mock-employer`,
  `mock-core-banking`, `mock-los`): independent FastAPI apps, each a single self-contained
  `main.py` (see docs/adr/0010 decision 2 for why), covering the golden-path response, at least
  one data-scenario variant, and at least one fault-injection scenario. `mock-los` is stateful
  (in-memory case store) and represents the external loan-origination system this platform
  augments rather than replaces (master instruction §3).
- **Object storage**: `ObjectStore` port with mandatory `tenant_id` on every method,
  `S3ObjectStore` (aioboto3/MinIO) enforcing tenant isolation via key-prefixing, bucket
  versioning, SHA-256 checksums stored as object metadata, and presigned download URLs. Wired
  into the composition root and `/health/ready` (now three checks: secret_provider, postgres,
  object_store).
- **Compose**: `minio` service added to `core`; a new `synthetic-systems` profile (folded into
  `full`) runs all five mock services from the existing API image via an `entrypoint` override,
  no new Dockerfiles needed.

## Evidence

| Gate | Command | Result |
|---|---|---|
| Lint | `ruff check src apps tests services` | All checks passed |
| Types | `mypy src apps` + per-package/per-service `mypy --explicit-package-bases` (see Makefile `typecheck`) | Clean across 85 + 13 + 5×1 source files |
| Import direction | `lint-imports` | 3 contracts kept, 0 broken |
| Unit + property tests | `make test` | 111 passed |
| Contract tests | `pytest tests/contract` (no Docker) | 24 passed |
| Integration tests | `make test-integration` (Postgres + MinIO via testcontainers) | 12 passed |
| Combined coverage | `make coverage-check` | 94% (gate: 90%) |
| SAST | `bandit -r src apps services` | 0 findings |
| Dependency audit | `pip-audit --skip-editable` | No known vulnerabilities |
| Full stack | `docker compose --profile full up --build` | postgres/minio/migrate/api/worker/all 5 mock services reach healthy; `/health/ready` reports all three checks healthy; live smoke-tested a `/credit-report` call through the running `mock-bureau` container |

## Real bugs found and fixed during this phase

1. **Non-deterministic transaction history.** `generate_transaction_history` anchored dates to
   `datetime.now(UTC)`, silently breaking the "same scenario+index → same output" guarantee every
   other generator provides. Caught by this module's own determinism test. Fixed with a fixed
   `_DEFAULT_REFERENCE_TIME` anchor, overridable via an explicit `reference_time` parameter.
2. **`ObjectStore.ensure_ready()` could crash-loop the API.** Calling it unconditionally at
   startup meant a briefly-unreachable MinIO would fail the whole process rather than starting
   degraded and reporting through `/health/ready` -- caught because a unit test with no live MinIO
   hung, then failed outright, before the fix. Now wrapped in try/except with a warning log.
3. **botocore's default timeouts/retries turned an unreachable-MinIO call into an ~80 second
   hang** in this project's own test suite -- a direct instance of the "never rely on library
   defaults" timeout requirement (master instruction §20). Fixed with an explicit, short
   `botocore.config.Config` (`connect_timeout`/`read_timeout`/`retries={"max_attempts": 1}`), with
   separate production (5s) and test (0.1s, dependency expected absent) timeout values.

## Known limitations / accepted at this phase

- The scenario catalog covers a representative subset (10 entries), not the full evaluation
  golden-dataset taxonomy from master instruction §21.2 (contradictory documents, prompt-injection
  payloads, protected-cohort cases). Those are added when Phase 9's evaluation harness exists to
  consume them -- adding them earlier would be untested, unused catalog entries.
- `mock-los`'s case store is in-memory and resets on container restart. Acceptable for a mock
  external system; it is never the platform's own system of record.
- The synthetic PDF documents are structurally valid but not designed to be OCR-friendly (no
  embedded fonts beyond the PDF standard Helvetica reference, no scanned-image noise model).
  Real OCR/extraction fixtures are Phase 4 scope.
- No `services/mock-*` Dockerfile was created; all five mock services and the API/migrate jobs
  share the one `Dockerfile` image via an `entrypoint` override in compose. This is intentional
  (docs/adr/0010 decision 2's sibling reasoning) but means the mock-service images carry the API's
  full dependency set rather than a minimal one -- acceptable for a demo/test double, would be
  revisited if these ever needed independent scaling or a smaller attack surface.

## Next phase

**Phase 3 — Durable workflow and intake**: Temporal workflows/activities, signals, retries,
versioning, replay tests; intake, submission, document upload, case status; Kafka events and
projections; initial reviewer queue creation -- per docs/architecture/phase-0-assessment.md §5.
