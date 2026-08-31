# ADR-0004: Local `make`-driven CI gate for Phase 1A; Tekton pipeline-as-code deferred to Phase 9/10

## Status
Accepted

## Context
§7 requires "Tekton or another self-hostable open-source CI engine" for "reproducible lint, test,
scan, build, sign, attest, deploy gates." No Kubernetes cluster exists in this engagement (see
Phase 0 assumption A3/A5), and Tekton requires a cluster control plane to run. Claiming a live
Tekton pipeline is "enforcing" gates it cannot actually execute would violate the instruction's
own rule against unverifiable production-readiness claims.

## Decision
- Phase 1A ships a `Makefile` with `lint`, `typecheck`, `test`, `security` (Bandit/pip-audit),
  and a composite `ci` target that runs all of them and fails the build (non-zero exit) on any
  violation. Pre-commit hooks run the fast subset locally.
- Phase 9/10 delivers a Tekton `Pipeline`/`Task` definition (`infra/gitops/tekton/`) that runs the
  identical `make` targets inside cluster-native tasks, plus build/sign/attest/deploy stages, so
  the *pipeline-as-code* is real and reviewable from day one even before a cluster exists to run
  it. When a cluster is available, this ADR's status should be updated to reflect that the pipeline
  is actually executing, with a link to a passing run.
- Until a live CI runner exists, `make ci` passing locally is the accepted evidence for the
  "CI gates" bullet in each phase's acceptance checklist. This is recorded explicitly so it is
  never silently reinterpreted as "CI is enforced in a shared environment" when it isn't yet.

## Consequences
- No false claim of enforced, tamper-resistant CI until a real runner exists.
- Slightly more manual discipline required from the operator running `make ci` before each phase
  is marked accepted — mitigated by pre-commit hooks catching most issues pre-commit.

## Alternatives considered
- **GitHub Actions now** — rejected as the *primary* gate because the repository has no GitHub
  remote configured in this engagement and the instruction's baseline is self-hostable CI; can be
  added later as a thin wrapper calling the same `make` targets if/when a remote is configured,
  without changing the underlying gate logic.
- **Claim Tekton is "configured" via YAML alone** — rejected per §28 ("provides ... without
  provisioned ... claims production readiness based on code coverage alone"-style false assurance).
