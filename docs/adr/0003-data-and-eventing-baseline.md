# ADR-0003: PostgreSQL as system of record; Qdrant/Valkey/Kafka/MinIO as bounded supporting stores

## Status
Accepted (PostgreSQL/compose wiring starts Phase 1B; Qdrant/Kafka/MinIO start Phase 2-6)

## Context
§7 and §10 mandate PostgreSQL as the transactional system of record, Qdrant for versioned policy
retrieval, Valkey for cache/coordination only (never authoritative), Kafka+Strimzi+Apicurio for
domain events via outbox/inbox (never dual-write), and MinIO for immutable versioned documents.

## Decision
- **PostgreSQL** owns every authoritative fact: applications, documents' metadata, verification
  results, policy evaluations, affordability results, risk signals, recommendations, human
  decisions, audit events, outbox/inbox. Schemas per bounded context as enumerated in §10.1.
  Row-level security enforces tenant isolation at the database layer, not only in application code.
- **Qdrant** stores only *derived, rebuildable* policy-corpus embeddings with mandatory
  tenant/product/jurisdiction/version payload filters. Never a source of truth for what a policy
  says — only for finding candidate evidence.
- **Valkey** stores caches, rate-limit counters, short-lived locks, TTL'd workflow hints. A total
  Valkey data loss must never lose a decision, case, or audit fact — this is verified by a Phase 9
  chaos test that flushes Valkey mid-case and asserts no consequential data loss.
- **Kafka** (via Strimzi in prod) carries versioned domain events for analytics/notifications/
  projections, populated exclusively through the transactional outbox pattern (an outbox row is
  written in the same DB transaction as the domain-state change; a relay process publishes it).
  Consumers deduplicate via an inbox table keyed on `event_id`.
- **MinIO** stores original synthetic documents and derived artifacts as immutable, versioned,
  checksummed objects; the API/browser only ever receives short-lived signed URLs, never bucket
  credentials.

## Consequences
- Single relational transaction boundary for anything consequential — no distributed transaction
  framework needed, directly satisfying invariant §5.6/§5.7.
- Outbox/inbox adds a small amount of eventual-consistency latency between a DB commit and the
  corresponding Kafka event being visible — acceptable because nothing authoritative depends on
  Kafka delivery timing.
- Qdrant and Valkey being explicitly non-authoritative means either can be wiped and rebuilt from
  Postgres/object storage without data loss — this is treated as a designed recovery path, not an
  afterthought.

## Alternatives considered
- **Dual-write to Postgres and Kafka directly** — explicitly rejected by §6.2 and §28 (inconsistent
  on partial failure; no exactly-once story).
- **Using Valkey/Redis as case-state store for speed** — explicitly rejected by §28.
- **Storing documents as DB bytea blobs** — rejected: no native versioning/lifecycle policy, poor
  operational story for large binaries, breaks the immutable-object-with-checksum requirement.
