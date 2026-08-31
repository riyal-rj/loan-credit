# ADR-0006: Self-hosted LiteLLM as the only LLM egress path; local vLLM default, Groq/OpenAI optional

## Status
Accepted (design now; implemented Phase 6)

## Context
§16 requires every model call to go through a self-hosted LiteLLM gateway using stable
task-oriented aliases, with local vLLM as the default provider and Groq/OpenAI as optional,
independently-gated deployments behind the same aliases. Application/agent code must stay
provider-neutral.

## Decision
- `src/finassist/ai/gateway/` defines a single `LlmGatewayClient` that calls LiteLLM's OpenAI-
  compatible endpoint using **task aliases only** (`underwriting-extraction-fast`,
  `underwriting-reasoning-approved`, `underwriting-evaluation-judge`, `policy-embedding`,
  `policy-reranker`) — never a raw provider/model string sourced from user or agent input.
- LiteLLM configuration (`infra/observability`/`infra/compose` LiteLLM config, added Phase 6) maps
  each alias to local vLLM by default; Groq/OpenAI deployments are added to the same alias's
  fallback list only when `GROQ_API_KEY`/`OPENAI_API_KEY` are present in OpenBao/env **and** an
  explicit feature flag enables that specific task+provider combination.
- Upstream provider keys live only in OpenBao and are injected into the LiteLLM deployment;
  application workloads hold only a scoped LiteLLM virtual key.
- Every gateway call is wrapped with timeout, bounded retry (idempotent requests only, preserving
  request ID/trace), circuit breaker, and per-tenant/case budget enforcement, with route/failover
  outcome recorded to Langfuse and the governance `model_invocations` table (not Langfuse alone —
  Langfuse is not the audit system of record per §28).

## Consequences
- A provider outage degrades to "route disabled, human review" rather than an application-code
  branch — application/agent code never learns which provider served a request.
- Enabling a hosted provider is a configuration + governance action (flag + keys + passed release
  gates), never a code change, satisfying §16's "never select models by arbitrary runtime strings."

## Alternatives considered
- **Call OpenAI/Groq SDKs directly from agent code "for now, swap later"** — explicitly rejected by
  §16 ("must never call Groq, OpenAI, or vLLM directly") and §28.
- **Bake provider selection into LangGraph node config** — rejected: recreates provider-specific
  branching in application code, which the gateway abstraction exists to prevent.
