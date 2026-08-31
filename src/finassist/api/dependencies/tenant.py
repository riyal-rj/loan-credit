"""Tenant-ID extraction for route handlers (Phase 3, first real API routes).

Master instruction §11: "Do not accept tenant IDs from request bodies as authoritative when they
are available from the authenticated context." There is no authenticated context yet -- Keycloak
OIDC lands in Phase 9 (docs/adr/0005 dev-only `AuthorizationProvider` stub) -- so this reads
`X-Tenant-Id` from the request header rather than the body as the interim source, and is the one
place that changes when Phase 9 replaces it with a claim pulled from a verified JWT.
"""

from __future__ import annotations

from fastapi import Header

from finassist.domain.shared.identifiers import TenantId


async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-Id")) -> TenantId:
    return TenantId(x_tenant_id)
