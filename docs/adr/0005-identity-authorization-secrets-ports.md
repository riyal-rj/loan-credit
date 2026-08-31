# ADR-0005: Identity/authorization/secrets as ports from Phase 1A; Keycloak/OPA/OpenBao adapters in Phase 9

## Status
Accepted

## Context
§18 mandates Keycloak (OIDC/PKCE), OPA (centralized RBAC/ABAC, deny-by-default), and OpenBao
(secrets, dynamic credentials) as the security baseline. These are heavy pieces of infrastructure.
§28 forbids hard-coded secrets and forbids skipping authorization checks. Phase 1A (§25) explicitly
scopes only "security-safe configuration and secret-provider ports" — full identity/authz
infrastructure is Phase 9.

## Decision
Define the ports now, in `src/finassist/security/ports.py`:
- `SecretProvider` (Protocol): `get_secret(name) -> str`, async, no plaintext logging ever.
- `AuthenticationContext` (typed value object): subject, tenant_id, roles, auth method,
  authenticated_at — constructed only by an `AuthenticationProvider` port, never by hand from
  request data.
- `AuthorizationDecision` (Protocol boundary): `AuthorizationProvider.check(subject, action,
  resource, context) -> Decision` with an explicit `Decision(allowed: bool, reason: str)` — no
  boolean-only API, so a deny always carries a reason for audit.

Phase 1A ships exactly one implementation of each port: environment-variable-backed
`EnvSecretProvider` (dev only, refuses to start if a "production" environment flag is set and it's
still the active provider — enforced by settings validation) and a dev `StaticAuthProvider` used
only by local tooling/tests, never wired into a code path that a real reviewer/officer role could
reach without Phase 9's Keycloak/OPA adapters replacing it. This keeps every downstream module
(API dependencies, application services) coded against the port from day one, so swapping in
Keycloak/OPA/OpenBao in Phase 9 is an adapter change, not a call-site rewrite.

## Consequences
- No module anywhere imports `keycloak`/`opa`/`openbao` SDKs before Phase 9 — verified by the
  Phase 1A import-linter contract, which already forbids infra imports outside `infrastructure/`
  and `security/`.
- The dev stub is clearly named (`Env*`, `Static*`) and isolated so it cannot be mistaken for a
  production-capable implementation, and a settings-layer guard makes using it under
  `ENVIRONMENT=production` a fail-fast startup error rather than a silent security gap.

## Alternatives considered
- **Defer the ports entirely until Phase 9** — rejected: every subsequent phase's code (API
  middleware, review actions) would otherwise be written against no abstraction and require a
  disruptive rewrite later, risking the "existing-file modifications" discipline required by §26.
- **Implement a toy in-process JWT issuer "for now"** — rejected: encourages treating the dev stub
  as good enough, increasing the chance it leaks into a real deployment path.
