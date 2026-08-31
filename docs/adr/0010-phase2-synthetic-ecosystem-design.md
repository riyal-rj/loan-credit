# ADR-0010: Phase 2 synthetic ecosystem — scenario catalog, mock service packaging, object-store isolation

## Status
Accepted

## Context
Phase 2 (master instruction §25) needed a synthetic data generator/scenario catalog, five mock
enterprise services (LOS, KYC, bureau, employer, core-banking) with deterministic fault injection,
and the object-storage document lifecycle. Several concrete design choices needed to be made that
the master instruction leaves open.

## Decisions

**1. `services/` holds test/demo tooling, not production code; the object store is real
production infrastructure and lives in `src/finassist/` instead.** The synthetic data generator
and mock services will never run in a real deployment (they stand in for systems FinAssist doesn't
own), so they live under `services/`, outside the `finassist` package the wheel ships. Object
storage, by contrast, will hold real (synthetic-applicant) documents once Phase 4 builds the
Document aggregate, so it belongs in `src/finassist/application/ports/object_store.py` +
`src/finassist/infrastructure/object_store/` like every other production port/adapter pair.

**2. Mock service directories stay hyphenated (`services/mock-kyc/`, matching the master
instruction's repository tree literally); each is a single self-contained `main.py`, not a
`schemas.py` + `main.py` split.** A hyphenated directory name isn't a valid Python identifier, so
it can never be dotted-imported (`services.mock-kyc` is a syntax error). Splitting each service
into two files would need inter-file imports that only work by manipulating `sys.path`/
`sys.modules` per service to avoid every service's `schemas.py` colliding under the same bare
module name — fragile in a way a single self-contained file entirely avoids. Contract tests load
each `main.py` by file path via `importlib.util.spec_from_file_location` under a unique module
alias (`tests/contract/conftest.py`), sidestepping the same problem for test collection. `mypy`
has the identical collision issue and is run once per mock-service file via
`--explicit-package-bases` rather than once across all of `services/` (see the Makefile's
`typecheck` target).

**3. Scenario resolution is a request header (`X-Synthetic-Scenario`), not a body field.** A mock
service's request schema should look like the real domain payload it stands in for (a real bureau
API has no `scenario_id` field); putting test-control state in a header keeps that payload honest
while still letting a caller (a test, or a later phase's workflow activity) select deterministic
behavior. Omitting the header defaults to `NORMAL_ELIGIBLE`.

**4. One `Scenario` catalog entry can specify either synthetic *data* behavior or a *fault* to
inject, not both as separate axes.** `services/synthetic_data/scenarios.py`'s `Scenario.fault`
field defaults to `NONE`; fault scenarios (`BUREAU_SERVICE_TIMEOUT`, `KYC_SERVICE_ERROR`, ...) are
just catalog entries like any data scenario. This keeps "what scenario am I in" a single lookup
rather than two independent selectors a caller could combine into combinations nobody tested.

**5. Object-store tenant isolation is enforced by mandatory key-prefixing in the adapter, not by
an optional parameter.** Unlike PostgreSQL (row-level security, docs/adr/0009), S3-compatible
storage has no per-tenant policy engine; `ObjectStore.put_object`/`get_object`/etc. all require
`tenant_id`, and `_scoped_key()` is the only place a physical object key is constructed, prefixing
every key with the tenant ID and rejecting path-traversal segments (`..`, leading `/`). An
integration test (`tests/integration/test_object_store.py::test_tenant_isolation_same_key_
different_tenants`) proves two tenants using the identical logical key never collide.

**6. `ObjectStore.ensure_ready()` failing at startup logs a warning and continues; it must never
crash-loop the API.** The first implementation awaited `ensure_ready()` unconditionally in the API
lifespan with no guard -- if MinIO was briefly unreachable, the whole process would fail to start
rather than come up degraded and report it via `/health/ready`, exactly the resilience anti-
pattern master instruction §20 asks to avoid. Caught by this project's own test suite hanging;
fixed by wrapping the call in try/except and letting the readiness check (which does have a
tenant-agnostic connectivity probe) be the source of truth for "is the dependency up."

**7. Every object-store network call uses explicit, short timeouts and no automatic retries
(botocore `Config(connect_timeout=..., read_timeout=..., retries={"max_attempts": 1})`).**
botocore's defaults turned one unreachable-MinIO test into an ~80 second hang -- a direct, now-
proven instance of the "never rely on library defaults" timeout requirement in master instruction
§20. Production and test configurations use different timeout values (`object_store_request_
timeout_seconds`, 5s prod / 0.1s in unit tests that expect the dependency to be absent), never the
library default.

## Consequences
- Adding a sixth mock service or a new scenario is additive (a new file / a new catalog entry),
  never a change to the loading mechanism.
- The object store's tenant isolation is testable and tested without needing a policy engine.
- Every dependency this phase added (Postgres in 1B, now MinIO) has surfaced at least one real
  "library defaults are dangerous" bug before reaching a shared environment -- treated as
  validation that testing against real infrastructure, not mocks-of-mocks, is worth the cost.

## Alternatives considered
- **A `minio` Python SDK adapter instead of `aioboto3`/S3 API** -- rejected: the application needs
  an async client, and `aioboto3` is the same S3-compatible API surface real AWS S3 uses, keeping
  the door open to a non-MinIO S3-compatible backend later without an adapter rewrite.
- **Combining mock services into one multi-route FastAPI app** -- rejected: these represent five
  genuinely separate external systems in the real architecture (§6.1's "Synthetic-system
  services"); one process would blur a boundary the rest of the design (independent health,
  independent fault injection, independent scaling) depends on being real.
