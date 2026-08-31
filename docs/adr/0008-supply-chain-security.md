# ADR-0008: Supply-chain security tooling (SBOM, scanning, signing, provenance)

## Status
Accepted (design now; enforced starting Phase 1A for dependency/container scanning, full
signing/attestation/provenance in Phase 9)

## Context
§7/§18/§27 require SBOM generation, dependency/image/IaC scanning, image signing and verified
provenance as release gates, not optional extras.

## Decision
- **Phase 1A**: `pip-audit` and `Bandit` run in `make security` and the composite `make ci` target
  against the application dependency set and source tree; Dockerfile is a non-root, multi-stage,
  minimal-base build scanned locally with Trivy as part of the same target.
- **Phase 9**: add Syft (SBOM generation), Grype (image/SBOM CVE scanning), Cosign (image signing
  and verification), and Gitleaks (secret scanning in history and pre-commit), wired into the
  Tekton pipeline from ADR-0004, with signature verification enforced at deploy time via an
  admission policy in the Kubernetes manifests (Phase 10).
- No critical/high finding is "accepted" silently — an accepted-risk finding must be recorded with
  owner, justification, and expiry in `docs/threat-model/accepted-risks.md` (created Phase 9).

## Consequences
- Dependency/secret hygiene is enforced from the very first commit, before the heavier
  image-signing pipeline exists, so bad habits don't accumulate for nine phases before being
  caught.

## Alternatives considered
- **Defer all scanning to Phase 9** — rejected: §28 rejects "supplies ... untested configuration,"
  and nine phases of unscanned dependencies would be exactly that.
