# ADR-0012: Phase 4 document intelligence and cross-source verification design

## Status
Accepted

## Context
Phase 4 (master instruction §25, "Document intelligence and verification") needed file safety,
OCR/parsing, classification, extraction, provenance, cross-source verification and a contradiction
model, reviewer evidence data, and extraction/verification evaluations. Real NLP/LLM-based
extraction is explicitly Phase 6 scope (the LLM gateway does not exist yet), so this phase had to
decide what "document intelligence" means without one, and how far to take the four mock external
systems (Phase 2) that had never actually been called by the main application.

## Decisions

**1. Extraction is deterministic regex matching against the known Phase 2 synthetic document
templates, not ML/LLM-based -- and is explicit about that limitation rather than dressed up as
general document AI.** `RegexDocumentExtractor` only recognizes the exact pay-stub/identity-
document layout `services/synthetic_data/documents.py` generates; an unrecognized document
classifies as `UNKNOWN` and yields zero facts, never a fabricated guess. `confidence=1.0` on a
match is honest, not optimistic: there is no probabilistic uncertainty in a regex match the way
there is in real OCR/NLP extraction. The `DocumentParser`/`DocumentExtractor` ports and the
`extracted_facts` data model (value/normalized value/confidence/page/extraction method/extractor
version/source checksum -- master instruction §15) are the seam Phase 6 replaces; nothing upstream
or downstream of that seam needs to change when it does.

**2. Only PDF is parsed this phase; images are validated but rejected at parse time with a clear
error, not silently skipped.** `StubFileSafetyScanner` accepts PNG/JPEG at the file-safety layer
(extension allowlist, magic-byte sniff) so a later phase adding real image OCR is a parser
addition only, never a validation-layer change -- but `PyPdfDocumentParser.extract_text` raises
`UnsupportedDocumentTypeError` for them today, matching what Phase 2 actually generates (PDF
only).

**3. File-safety checks are real (extension, magic-byte MIME sniff, size, PDF page count,
encryption detection); only the malware-signature check is a dev-only stub that always reports
clean.** The same "dev-only, real adapter deferred" pattern as `SecretProvider`/
`AuthorizationProvider` (ADR-0005): a real ClamAV (or equivalent) integration is Phase 9 (security
hardening) scope. `UploadDocumentHandler` (Phase 3) now calls the scanner before anything is
stored, and stores the scanner's *detected* content type, never the client-declared one -- the
same "don't trust caller-supplied metadata" rule the scanner itself enforces internally.

**4. Cross-source verification only produces a match/contradiction verdict for KYC and employer;
bureau and core-banking calls happen but are stored as raw response snapshots, not fact
comparisons.** KYC and employer are the two mock services where a document-extracted fact has
something to compare against (identity-document facts vs `/verify`; pay-stub facts vs
`/verify-employment`). Bureau (`/credit-report`) and core-banking (`/transaction-history`) are
still called -- matching master instruction §3's "cross-checks facts across ... mock KYC, mock
bureau, mock employer, and mock transaction systems" -- but there is no document-extracted
"declared credit score" to contradict a bureau response against; their responses are captured in
`verification.external_response_snapshots` for Phase 5's affordability/risk engines to consume.

**5. A verification check whose required facts were never extracted becomes `INSUFFICIENT_
EVIDENCE`, not a silently skipped/missing entry.** Master instruction §9's Verification Agent must
never "resolve contradictions without evidence," and invariant §5.10 requires low-confidence/
guardrail cases to route to human review -- an unresolved check is exactly as reportable as a
resolved one, so `VerifyApplicationFactsHandler` always records one `VerificationCheck` per
external system it *could* have called, with `INSUFFICIENT_EVIDENCE` standing in for "the fact
this check needs was never extracted" rather than that case being indistinguishable from "we never
looked."

**6. Verification uses the applicant's own intake-declared name/date-of-birth (`Applicant.
given_name`/`family_name`/`date_of_birth`, captured at `POST /applications`) for the KYC/bureau
calls' identity fields, and document-extracted facts only for what intake never captures
(synthetic ID, address, employer, income).** This avoids ambiguity about "which name/DOB to use"
when a document's extracted values could themselves be wrong -- the check is "do external systems
recognize the identity already on file," not "do two extracted values agree with each other."

**7. `ApplicationWorkflow` gains two new activities (`extract_document_facts_activity`,
`verify_facts_activity`) between the existing document-presence check and escalation, and
`enter_human_review_activity` becomes its own activity again (reintroduced from the shared
`_enter_human_review` helper Phase 3 inlined) so the workflow can pass a real, verification-derived
reason instead of a placeholder string.** `AdvanceDocumentProcessingHandler`'s has-docs branch now
stops at `VERIFICATION` instead of auto-escalating (docs/adr/0011's Phase 3 version escalated
unconditionally, before there was anything to verify). The zero-documents branch is unchanged --
still escalates directly, since there is nothing to extract or verify without a document.

**8. `extract_document_facts_activity` processes every document uploaded for the application in
one activity invocation, not one activity per document.** Temporal activities are the unit of
retry; letting the workflow loop per-document over dynamically-discovered document IDs would need
an extra activity just to list them, for no benefit. Idempotency is preserved per document by
suffixing the shared `workflow_id:activity_id` key with the document's own ID
(`activities.py::_idempotency_key`), so a retried activity invocation that partially completed
(some documents already processed) skips only the ones it already finished.

**9. `GET /applications/{id}/evidence`** (named explicitly in master instruction §11's minimum API
list) **returns extracted facts and verification verdicts with citations; it does not render
them.** Side-by-side document/evidence rendering (master instruction §17) is Phase 7's reviewer
UI.

## Consequences
- Every application that reaches `AWAITING_HUMAN_REVIEW` after Phase 4 carries a real, specific
  reason (verification match/contradiction/insufficient-evidence summary) instead of Phase 3's
  "no automated engine exists yet" placeholder -- directly reusable as Phase 5/6's real
  reason-code surface once automated policy/affordability/fraud/risk exists.
- Phase 5's affordability engine has real income/employment verification data
  (`verification_checks`, `external_response_snapshots`) to consume instead of having to invent a
  first data source.
- Adding real image OCR or a real ML extraction model later is additive at the port boundary
  (`DocumentParser`/`DocumentExtractor`), not a rewrite of the workflow, the persistence schema, or
  the verification comparison logic.
- Alembic revision IDs must stay at or under 32 characters (`alembic_version.version_num` is
  `VARCHAR(32)`) -- this migration's first draft didn't, and failed `alembic upgrade head` with a
  real `StringDataRightTruncationError`, caught by the integration test suite rather than by
  review. Recorded directly in the migration file so the next phase doesn't repeat it.

## Alternatives considered
- **A real OCR/NLP extraction library (e.g. a local layout-aware model) instead of regex
  matching** -- rejected for this phase: master instruction §16 requires all LLM access to go
  through the self-hosted LiteLLM gateway, which doesn't exist until Phase 6; adopting a
  general-purpose extraction dependency now would be replaced wholesale in two phases regardless,
  for a corpus (10 synthetic scenarios) small enough that regex extraction is completely adequate.
- **Comparing extracted identity-document facts against the applicant's own intake-declared
  fields** (self-consistency, "does the ID match what was typed at signup") **instead of only
  calling out to KYC** -- not rejected, but deferred: nothing in this phase's scope needs it yet,
  and it can be added as a fifth check without touching the existing four.
- **Treating a missing-fact verification check as simply absent from the results** (no entry)
  **instead of an explicit `INSUFFICIENT_EVIDENCE` verdict** -- rejected: indistinguishable from
  "verification wasn't attempted," which master instruction §9 explicitly forbids papering over.
- **One Temporal activity per uploaded document** -- rejected: no benefit over one activity
  iterating every document, given documents must already be listed via a query either way, and it
  would add workflow-level looping complexity (dynamic activity fan-out) for no correctness gain.
