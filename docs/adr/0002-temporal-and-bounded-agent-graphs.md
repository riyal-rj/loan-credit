# ADR-0002: Self-hosted Temporal as macro-orchestrator; bounded typed state graphs inside activities

## Status
Accepted (design now; implemented starting Phase 3/6)

## Context
§13 requires a durable workflow engine for case orchestration with deterministic workflow code,
idempotent activities, signals/timers for human waits, and replay-safe versioning. §9/§13 require
any agent reasoning (LangGraph or equivalent) to run only inside bounded activities with finite
steps, never as a second authoritative orchestrator.

## Decision
- One Temporal workflow execution maps to one application version (an application resubmission
  after `NEEDS_MORE_INFORMATION` starts a new, linked workflow execution referencing the prior one
  — never mutates a closed execution's history).
- All network/DB/LLM/random/clock calls live in activities; workflow code contains only
  deterministic control flow over activity results and signals.
- Every activity is idempotent via a stable operation key (`{application_id}:{activity_name}:
  {input_hash}`) recorded in the `governance.tool_calls` / `integration.idempotency_keys` tables.
- Human waits (review assignment, decision, additional-information response) are Temporal signals
  with durable timers for SLA/escalation — not polling loops.
- Agent reasoning (bounded state graph) executes as one Temporal activity per agent step-bundle,
  with the graph's own step/time/token budget enforced independently of Temporal's retry policy,
  so a runaway agent cannot be "helped" by infrastructure-level retries into unbounded cost.
- Workflow versioning uses Temporal's patching API; old in-flight histories are replay-tested in CI
  before a new worker deployment is allowed to serve them.

## Consequences
- Case state is recoverable across worker crashes/deploys without manual reconciliation.
- Replay tests become a hard release gate (§27), which forces workflow code to stay
  side-effect-free by construction rather than by discipline alone.
- Adds operational surface (Temporal server + persistence store) — accepted because the
  alternative (hand-rolled saga/state-machine-in-Postgres-with-cron-poller) reimplements the same
  guarantees worse and without replay.

## Alternatives considered
- **Celery/cron-driven state machine in Postgres** — rejected: no built-in replay, weaker exactly-
  once activity semantics, human-wait timers become fragile polling.
- **LangGraph (or similar) as the top-level case orchestrator** — explicitly rejected by §13
  ("must not become a second authoritative case-workflow engine") and by §28's rejection of
  "a chain of agents with no durable state, typed contracts, bounds, or replay."
