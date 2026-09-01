# Phase 4 Completion Report — Document Intelligence and Verification

Status: **Accepted**
Date: 2026-08-31

## Scope delivered

Per the master instruction's Phase 4 bullets ("Document intelligence and verification") and
docs/architecture/phase-0-assessment.md §5:

- File safety: extension/MIME-signature/size/page-count/encryption checks, plus a dev-only
  malware-scan stub (`src/finassist/infrastructure/documents/file_safety_scanner.py`)
- OCR/parsing: real PDF text-layer extraction via `pypdf`
  (`src/finassist/infrastructure/documents/pdf_parser.py`)
- Classification and fact extraction: deterministic regex matching against the known Phase 2
  synthetic document corpus, with full provenance (`src/finassist/infrastructure/documents/
  regex_extractor.py`, `src/finassist/domain/documents/`)
- Cross-source verification and a contradiction model against the four Phase 2 mock external
  systems, actually called by the main application for the first time
  (`src/finassist/application/commands/verify_application_facts.py`,
  `src/finassist/infrastructure/external_systems/`, `src/finassist/domain/verification/`)
- Reviewer evidence data (not rendering -- Phase 7's UI): `GET /applications/{id}/evidence`
- `ApplicationWorkflow` now runs real document intelligence and verification between the
  document-presence check and human-review escalation

Design rationale -- including three real bugs this phase's own tests caught -- is recorded in
docs/adr/0012.

## What was built

- **`domain/documents/`**: `ExtractedFact`/`FactType`/`DocumentClassification` value types,
  file-safety/extraction domain exceptions.
- **`domain/verification/`**: `VerificationCheck`/`VerificationVerdict`/`SourceSystem`.
- **Five new ports** (`application/ports/`): `FileSafetyScanner`, `DocumentParser`,
  `DocumentExtractor`, four external-verification Protocols (`KycVerifier`/`EmployerVerifier`/
  `BureauClient`/`CoreBankingClient`), `ExtractionRepository`, `VerificationRepository`.
- **Command handlers**: `process_document` (parse -> classify -> extract -> persist, one document
  at a time, idempotent), `verify_application_facts` (KYC/employer produce match/contradiction
  verdicts; bureau/core-banking captured as raw response snapshots for Phase 5), `enter_human_
  review` (reintroduced as its own idempotent command so the workflow can pass a real,
  verification-derived escalation reason). `upload_document` (Phase 3) now runs the file-safety
  scan before anything is stored.
- **Infrastructure**: `PyPdfDocumentParser`, `RegexDocumentExtractor`, `StubFileSafetyScanner`,
  four httpx-based mock-service adapters with explicit timeouts, two new Postgres repositories.
- **`ApplicationWorkflow`**: two new activities (`extract_document_facts_activity`,
  `verify_facts_activity`) inserted between the document-presence check and escalation; `Advance
  DocumentProcessingHandler`'s has-docs branch now stops at `VERIFICATION` instead of
  auto-escalating, so there is something to verify before the case reaches a human.
- **API**: `GET /applications/{id}/evidence` (master instruction §11's minimum API list).
- **Database**: migration `0003_phase4_documents` -- `documents` schema (`extraction_runs`,
  `extracted_facts`, `fact_candidates`, `document_checksums`) and `verification` schema
  (`verification_runs`, `verification_checks`, `contradictions`, `external_response_snapshots`)
  per master instruction §10.1's exact table list, all RLS-enabled.
- **Settings/Container**: document size/page/timeout limits, four mock-service base URLs, all
  wired into `/health/ready` (now eight checks).

## Evidence

| Gate | Command | Result |
|---|---|---|
| Lint | `ruff check src apps tests services` | All checks passed |
| Types | `mypy src apps` (strict) | Clean across 132 source files |
| Import direction | `lint-imports` | 3 contracts kept, 0 broken (161 files, 537 dependencies) |
| Unit + property tests | `make test` | 153 passed |
| Workflow tests | `make test-workflow` | 5 passed |
| Integration tests | `make test-integration` (real Postgres, real mock KYC/bureau/employer/core-banking services over real HTTP, real local Temporal dev server) | 17 passed |
| Combined coverage | `coverage report --fail-under=90` across all three layers | 92% (gate: 90%) |
| SAST | `bandit -r src apps services` | 0 findings |
| Dependency audit | `pip-audit --skip-editable` | No known vulnerabilities (after the `pypdf` upgrade below) |

## Real bugs found and fixed during this phase

1. **`pypdf==5.9.0` (the version originally pinned) carries 37 known CVEs**, all fixed by 6.x
   releases. Caught by `pip-audit`, not by review -- the initial `pyproject.toml` pin
   (`>=5.1,<6.0`) predates the vulnerability disclosures. Fixed by widening the pin to
   `>=6.16,<7.0` and re-verifying the parser against real synthetic PDFs (no API break for the
   subset this project uses).
2. **The migration's Alembic revision ID exceeded 32 characters**
   (`0003_phase4_documents_and_verification`, 38 chars) and failed `alembic upgrade head` with a
   real `StringDataRightTruncationError` -- `alembic_version.version_num` is `VARCHAR(32)`.
   Caught by the integration test suite's `_migrated_database` fixture, not by review (Phase 3's
   `0002_phase3_workflow_and_review` was already at the exact 32-char limit, unnoticed). Fixed by
   shortening the revision ID to `0003_phase4_documents` and documenting the constraint directly
   in the migration file.
3. **`SqlAlchemyExtractionRepository.add_run`/`SqlAlchemyVerificationRepository.add_run` inserted
   parent and child rows in one combined `flush()`, which let asyncpg's "insertmanyvalues"
   batching for the (usually multi-row) child insert execute before the single-row parent insert**,
   tripping `extracted_facts_run_id_fkey` -- a real, reproducible `ForeignKeyViolationError` this
   project's own integration test caught on a real Postgres container, not by review or by the
   (FK-unaware) in-memory fakes the unit tests use. Fixed by flushing after each row group a later
   group depends on, in both repositories.

## Known limitations / accepted at this phase

- **Extraction is deterministic regex matching against the known Phase 2 synthetic corpus, not
  general-purpose document AI.** An unrecognized document yields zero facts, never a fabricated
  guess. Real NLP/LLM-based extraction through the self-hosted LiteLLM gateway is Phase 6 scope;
  the `DocumentExtractor` port is the seam that phase replaces without touching anything upstream
  or downstream of it.
- **Only PDF is parsed.** Image documents (PNG/JPEG) pass file-safety validation but are rejected
  at parse time with a clear error -- real OCR is a parser addition for a later phase, not a
  validation-layer change.
- **Malware scanning is a dev-only stub that always reports clean.** A real ClamAV (or equivalent)
  integration is Phase 9 (security hardening) scope, matching the dev-only-adapter pattern already
  used for secrets/authorization (ADR-0005).
- **Only KYC and employer verification produce a match/contradiction verdict.** Bureau and
  core-banking responses are captured as raw snapshots for Phase 5's affordability/risk engines,
  since there is no document-extracted fact to contradict a credit score or transaction history
  against.
- **`documents.fact_candidates`/`documents.document_checksums` are schema-only**, same pattern as
  Phase 1B's `consent_records`: no writer needs them yet (the deterministic extractor never
  produces competing candidates; nothing does cross-application duplicate detection yet).
- **`GET /applications/{id}/evidence` returns data, not a rendered view.** Side-by-side
  document/evidence rendering (master instruction §17) is Phase 7's reviewer UI.

## Next phase

**Phase 5 — Deterministic policy, affordability, and anomaly services**: versioned policy
schema/engine/publication; decimal affordability calculators and stress scenarios; deterministic
anomaly signals and a bounded model adapter; boundary/property tests and reason codes -- per
docs/architecture/phase-0-assessment.md §5. Phase 4's verification checks and external-response
snapshots (bureau credit report, core-banking transaction history) are exactly the inputs Phase
5's affordability/risk engines consume; `ApplicationWorkflow`'s escalate-to-human-review step is
where those new automated activities are inserted, without changing the workflow's outer shape.
