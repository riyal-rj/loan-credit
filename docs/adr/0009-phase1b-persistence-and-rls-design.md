# ADR-0009: Phase 1B persistence design — RLS enforcement, audit hash chain, outbox scope

## Status
Accepted

## Context
ADR-0001/0003 already decided PostgreSQL is the system of record and that tenant isolation must
be structurally hard to omit (§5.8, §10.1). Phase 1B is the first phase that actually creates
tables, so this ADR records the concrete mechanics: how RLS is enforced from application code,
how the append-only audit log proves tamper-evidence, and how much of the outbox/inbox pattern is
built now versus deferred.

## Decisions

**1. RLS enforcement via a mandatory per-transaction session variable, not an app-layer filter.**
Every tenant-scoped table gets `ENABLE ROW LEVEL SECURITY` plus a `USING`/`WITH CHECK` policy on
`current_setting('app.tenant_id', true)::text = tenant_id`. The `SqlAlchemyUnitOfWork` sets
`SET LOCAL app.tenant_id = :tenant_id` as the first statement of every transaction, before any
other query runs, and refuses to open a transaction without a tenant ID. This makes it
*impossible* to accidentally return cross-tenant rows by forgetting a `WHERE tenant_id = ...`
clause in a repository method — the database refuses the row regardless of the query. The
apparently-tempting alternative (an app-level `tenant_id` filter added to every query) was
rejected exactly because that's the pattern that lets one missed clause become a data breach.

**2. Audit tamper-evidence via a hash chain on `audit.audit_events`, plus a per-tenant checkpoint
in `audit.audit_hashes`.** Each audit event stores `prev_hash` (the previous event's `hash` for
that tenant, or a fixed genesis value for the first) and `hash = sha256(prev_hash || canonical_json
(event fields))`. `audit.audit_hashes` holds one row per tenant with the latest `event_id`/`hash`,
so verifying the whole chain is intact is an O(n) scan anchored at a single trusted checkpoint
row, not a full-table linear-scan-and-hope. Audit events are append-only at the application layer
(no `UPDATE`/`DELETE` code path exists); a database-level `REVOKE UPDATE, DELETE` grant is deferred
to Phase 9's security hardening pass alongside the rest of the privilege model, but the
hash chain already makes silent tampering detectable even before that grant lands.

**3. Outbox table + same-transaction write now; the relay/publisher (Kafka producer) is Phase 3.**
`integration.outbox_events` is created and the application layer writes a row into it in the same
transaction as the domain-state change (satisfying §5.7/§28's "never dual-write" rule from day
one), but nothing reads and publishes those rows to Kafka yet -- Kafka itself doesn't exist until
Phase 3. This is intentionally the same "build the seam before the far end exists" approach ADR-
0005 used for secrets/auth: application code already writes outbox rows through
`UnitOfWork.outbox`, so adding the relay later is additive, not a call-site rewrite.
`integration.inbox_messages` (consumer-side dedup) and `integration.idempotency_keys`
(command-level dedup) are created now for the same reason, and idempotency keys are exercised
immediately by the `submit_application` command handler, which is the first place a retried
client request must not double-submit a case.

**4. SQLAlchemy 2.0 async ORM (not Core, not a raw-SQL layer).** Declarative mapped classes give
typed repository code and Alembic autogenerate support, at the cost of an ORM/domain-model
mapping layer (`infrastructure/postgres/orm_models.py`) kept deliberately separate from the domain
aggregates in `domain/applications/` -- the domain layer has zero SQLAlchemy imports (enforced by
the existing import-linter contract), and `SqlAlchemyApplicationRepository` is the only place that
translates between the two.

**5. `Applicant` is modeled as data owned by the `Application` aggregate's creation command, not
as its own aggregate with a repository, for Phase 1B.** Identity resolution/deduplication across
applicants is a Verification/Fraud concern (§8 context 3/7, Phase 4). Giving `Applicant` its own
aggregate and repository now, before there's any use case that looks one up independently of an
application, would be exactly the premature abstraction §22/23 warn against. Revisit when Phase 4
needs cross-application applicant matching.

## Consequences
- A repository method or raw query that forgets tenant scoping fails closed (returns nothing /
  errors) rather than leaking data -- verified directly by an integration test that opens two
  tenant contexts against the same database and asserts cross-tenant reads return empty.
- The audit hash chain adds a small write-side cost (compute one hash per event) in exchange for
  making undetected tampering require rewriting every subsequent event's hash for that tenant.
- Outbox rows will accumulate unpublished until Phase 3 adds the relay; this is expected and
  tracked, not a bug -- Phase 3's acceptance criteria include a bounded backlog check.

## Alternatives considered
- **Postgres schemas per tenant instead of RLS** -- rejected: doesn't scale operationally to an
  arbitrary tenant count without per-tenant migration fan-out, and the master instruction's
  baseline (§10.1) specifically calls for RLS "or an equally strong, centrally tested" strategy.
- **Soft-delete/mutate audit rows with an `is_corrected` flag** -- rejected by invariant §5.12
  ("audit history is append-only; corrections are new events, not destructive edits").
