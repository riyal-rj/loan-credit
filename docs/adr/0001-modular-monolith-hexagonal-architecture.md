# ADR-0001: Modular monolith with hexagonal architecture and DDD bounded contexts

## Status
Accepted

## Context
The master instruction (§4, §6.1, §8, §28) requires strict bounded contexts, dependency
inversion, and explicitly warns against "premature decomposition into dozens of independently
deployed microservices" while also rejecting "generic database dictionaries instead of a domain
model." The system has ~11 bounded contexts (identity, applications, documents, verification,
policy, affordability, fraud, risk synthesis, human review, governance, evaluation) and several
infrastructure integrations (Postgres, Qdrant, Valkey, Kafka, Temporal, object storage, LLM
gateway).

## Decision
Build one Python codebase (`src/finassist/`) organized as:
- `domain/<context>/` — pure domain model (entities, value objects, aggregates, domain services,
  domain exceptions). No FastAPI/SQLAlchemy/Kafka/Temporal/LangGraph/Langfuse imports allowed.
- `application/{commands,queries,services,ports}/` — use-case orchestration against `ports`
  (Protocols/ABCs), no concrete infrastructure imports.
- `infrastructure/<tech>/` — concrete adapters implementing `application/ports`.
- `ai/` — agents, tools, prompts, retrieval, gateway client, guardrails, evaluation. Agents call
  application services/ports, never raw infrastructure.
- `api/` and `apps/worker` — composition roots that wire concrete infrastructure into application
  services and expose them over HTTP / durable-workflow activities.

Independently deployable **processes** are limited to what has a real operational reason to scale
or fail independently: the API service and the workflow/document worker pool (§6.1). A bounded
context graduates to its own network service only when scaling, ownership, release cadence, fault
isolation, or a security boundary justifies it — and that decision must get its own ADR at the
time it happens.

Import direction is enforced mechanically (import-linter contract, added in Phase 1A CI) so the
rule survives contributor turnover instead of relying on code review memory.

## Consequences
- Cheap to reason about transactionally (one Postgres, real cross-aggregate transactions, no
  distributed-transaction complexity) which directly serves invariant §5.6 (deterministic,
  concurrency-safe state transitions).
- Extraction to a separate service later is mechanical: the bounded context already has no inward
  leakage from other contexts, because `domain/*` never imports another context's infrastructure.
- Risk: a modular monolith can rot into a "big ball of mud" without enforcement — mitigated by the
  import-linter gate being a CI failure, not a lint warning.

## Alternatives considered
- **Microservice-per-bounded-context from day one** — rejected per §28 explicit rejection
  criterion ("adds microservices without ownership/failure/scaling justification"); would also
  force distributed transactions across policy/affordability/evidence for a single case decision,
  directly risking invariant §5.6/§5.7.
- **Single flat FastAPI app with no domain layer** — rejected per §28 ("generic database
  dictionaries instead of a domain model").
