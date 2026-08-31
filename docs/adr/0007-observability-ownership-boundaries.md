# ADR-0007: Observability ownership — OpenTelemetry/Grafana own infra telemetry, Langfuse owns LLM traces, PostgreSQL audit owns decision lineage

## Status
Accepted (bootstrap now; full dashboards/alerts Phase 8)

## Context
§7's footnote and §19/§28 require explicit ownership when tools overlap, and explicitly reject
"treats Langfuse as the audit system of record" and "uses only application logs and calls that
monitoring."

## Decision
Three non-overlapping ownership domains, enforced by what each tool is allowed to be queried for
in documentation and dashboards:
1. **OpenTelemetry → Prometheus/Loki/Tempo/Grafana**: owns service and infrastructure
   observability — request rates/latency/errors, resource saturation, distributed traces across
   HTTP/DB/Kafka/Temporal/Qdrant/Valkey, structured logs.
2. **Langfuse**: owns LLM-specific traces — prompts, model calls, agent steps, retrieval/reranker
   calls, token/cost, offline evaluation datasets/experiments/scores. Pseudonymized, redacted.
3. **PostgreSQL `audit`/`governance` schemas**: owns the append-only, tamper-evident decision
   lineage — the only system a compliance replay is defined against. Langfuse/Grafana data can
   enrich an investigation but can never be the sole record a decision is reconstructed from.

Correlation IDs and W3C trace context tie all three together without duplicating authority: a
Grafana panel or Langfuse trace links to the audit event by `application_id`/`correlation_id`, it
never substitutes for it.

## Consequences
- A Langfuse or Prometheus outage degrades observability, not auditability or replayability.
- Every phase's "Operational impact" section must say, for any new telemetry, which of the three
  domains it belongs to — prevents accidental drift back into "logs are our monitoring."

## Alternatives considered
- **One unified observability backend for everything including audit** — rejected: LLM-trace
  tools and general telemetry backends are not built for tamper-evident, indefinitely-retained,
  replay-grade regulatory lineage; conflating them risks both perverse retention trade-offs and a
  single vendor/tool becoming a compliance single point of failure.
