"""`VerifyApplicationFactsCommand`: invoked by `verify_facts_activity`, never directly by the API.

Compares document-extracted facts against the four synthetic external systems (master instruction
§3: "Cross-checks facts across the application, documents, mock KYC, mock bureau, mock employer,
and mock transaction systems"). Only KYC and employer produce a match/contradiction verdict --
those are the two where an extracted fact has something to compare against (identity-document
facts vs `/verify`; pay-stub facts vs `/verify-employment`). Bureau and core-banking calls still
happen (when enough facts exist to call them meaningfully) but are stored as raw response
snapshots for Phase 5's affordability/risk engines, not fact comparisons -- there is no
document-extracted "declared credit score" to contradict them against (docs/adr/0012).

A check whose required facts were never extracted becomes `INSUFFICIENT_EVIDENCE`, not a skipped/
missing entry -- master instruction §9's Verification Agent must never "resolve contradictions
without evidence," and an unresolved check is exactly as reportable as a resolved one.
"""

from __future__ import annotations

from dataclasses import dataclass

from finassist.application.ports.external_verification import (
    BureauClient,
    CoreBankingClient,
    EmployerVerifier,
    KycVerifier,
)
from finassist.application.ports.id_generator import IdGenerator
from finassist.application.ports.unit_of_work import UnitOfWorkFactory
from finassist.application.ports.verification_repository import ExternalResponseSnapshot
from finassist.domain.applications.exceptions import ApplicationNotFoundError, DuplicateRequestError
from finassist.domain.documents.document_fact import FactType
from finassist.domain.shared.clock import Clock
from finassist.domain.shared.identifiers import ApplicationId, TenantId
from finassist.domain.verification.contradiction import (
    SourceSystem,
    VerificationCheck,
    VerificationVerdict,
)

_OPERATION_NAME = "verify_application_facts"
_MATCH_SCORE_THRESHOLD = 0.8
_INCOME_DEVIATION_THRESHOLD = 0.2


@dataclass(frozen=True, slots=True)
class VerifyApplicationFactsCommand:
    tenant_id: TenantId
    application_id: ApplicationId
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class VerifyApplicationFactsResult:
    checks: list[VerificationCheck]
    contradiction_count: int
    summary: str


def build_verification_summary(checks: list[VerificationCheck]) -> str:
    if not checks:
        return "no verification checks could be run: no identity/employment facts were extracted"
    matched = sum(1 for c in checks if c.verdict is VerificationVerdict.MATCHED)
    contradicted = [c for c in checks if c.verdict is VerificationVerdict.CONTRADICTED]
    insufficient = sum(1 for c in checks if c.verdict is VerificationVerdict.INSUFFICIENT_EVIDENCE)
    parts = [f"{matched} matched"]
    if contradicted:
        reasons = ", ".join(f"{c.source_system.value}: {c.detail}" for c in contradicted)
        parts.append(f"{len(contradicted)} contradicted ({reasons})")
    if insufficient:
        parts.append(f"{insufficient} insufficient evidence")
    return "verification complete: " + "; ".join(parts)


class VerifyApplicationFactsHandler:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        kyc_verifier: KycVerifier,
        employer_verifier: EmployerVerifier,
        bureau_client: BureauClient,
        core_banking_client: CoreBankingClient,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._kyc_verifier = kyc_verifier
        self._employer_verifier = employer_verifier
        self._bureau_client = bureau_client
        self._core_banking_client = core_banking_client
        self._id_generator = id_generator
        self._clock = clock

    async def handle(self, command: VerifyApplicationFactsCommand) -> VerifyApplicationFactsResult:
        async with self._uow_factory.begin(tenant_id=command.tenant_id) as uow:
            reserved = await uow.reserve_idempotency_key(
                key=command.idempotency_key, operation_name=_OPERATION_NAME
            )
            if not reserved:
                raise DuplicateRequestError(_OPERATION_NAME, command.idempotency_key)

            application = await uow.applications.get(
                tenant_id=command.tenant_id, application_id=command.application_id
            )
            if application is None:
                raise ApplicationNotFoundError(str(command.application_id))
            applicant = await uow.applicants.get(
                tenant_id=command.tenant_id, applicant_id=application.applicant_id
            )
            if applicant is None:
                raise ApplicationNotFoundError(str(command.application_id))

            stored_facts = await uow.extraction.get_facts_for_application(
                tenant_id=command.tenant_id, application_id=command.application_id
            )
            facts_by_type = {sf.fact.fact_type: sf.fact for sf in stored_facts}

            checks: list[VerificationCheck] = []
            snapshots: list[ExternalResponseSnapshot] = []

            synthetic_id = facts_by_type.get(FactType.SYNTHETIC_ID)
            street = facts_by_type.get(FactType.STREET_ADDRESS)
            city = facts_by_type.get(FactType.CITY)
            employer_name = facts_by_type.get(FactType.EMPLOYER_NAME)
            gross_monthly_income = facts_by_type.get(FactType.GROSS_MONTHLY_INCOME)

            if synthetic_id is not None and street is not None and city is not None:
                kyc_result = await self._kyc_verifier.verify_identity(
                    given_name=applicant.given_name,
                    family_name=applicant.family_name,
                    date_of_birth=applicant.date_of_birth,
                    synthetic_id=synthetic_id.normalized_value,
                    street_address=street.normalized_value,
                    city=city.normalized_value,
                )
                snapshots.append(
                    ExternalResponseSnapshot(
                        source_system=SourceSystem.MOCK_KYC,
                        response_payload={
                            "status": kyc_result.status,
                            "name_match_score": kyc_result.name_match_score,
                            "address_match_score": kyc_result.address_match_score,
                            "date_of_birth_match": kyc_result.date_of_birth_match,
                            "reference_id": kyc_result.reference_id,
                        },
                    )
                )
                matched = (
                    kyc_result.status == "PASS"
                    and kyc_result.date_of_birth_match
                    and kyc_result.name_match_score >= _MATCH_SCORE_THRESHOLD
                    and kyc_result.address_match_score >= _MATCH_SCORE_THRESHOLD
                )
                checks.append(
                    VerificationCheck(
                        source_system=SourceSystem.MOCK_KYC,
                        checked_fact_type=FactType.SYNTHETIC_ID.value,
                        declared_value=f"{applicant.given_name} {applicant.family_name}",
                        external_value=(
                            f"status={kyc_result.status} "
                            f"name_score={kyc_result.name_match_score:.2f} "
                            f"address_score={kyc_result.address_match_score:.2f}"
                        ),
                        verdict=(
                            VerificationVerdict.MATCHED
                            if matched
                            else VerificationVerdict.CONTRADICTED
                        ),
                        confidence=min(kyc_result.name_match_score, kyc_result.address_match_score),
                        detail=f"KYC reference {kyc_result.reference_id}",
                    )
                )
            else:
                checks.append(
                    VerificationCheck(
                        source_system=SourceSystem.MOCK_KYC,
                        checked_fact_type=FactType.SYNTHETIC_ID.value,
                        declared_value=None,
                        external_value=None,
                        verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                        confidence=0.0,
                        detail=(
                            "identity document facts (synthetic ID / address) were not extracted"
                        ),
                    )
                )

            declared_annual_income: int | None = None
            if gross_monthly_income is not None:
                declared_annual_income = round(float(gross_monthly_income.normalized_value) * 12)

            if synthetic_id is not None and employer_name is not None and declared_annual_income:
                employment_result = await self._employer_verifier.verify_employment(
                    given_name=applicant.given_name,
                    family_name=applicant.family_name,
                    synthetic_id=synthetic_id.normalized_value,
                    employer_name=employer_name.normalized_value,
                    declared_annual_income=declared_annual_income,
                )
                snapshots.append(
                    ExternalResponseSnapshot(
                        source_system=SourceSystem.MOCK_EMPLOYER,
                        response_payload={
                            "is_employment_confirmed": employment_result.is_employment_confirmed,
                            "verified_annual_income": employment_result.verified_annual_income,
                            "tenure_months": employment_result.tenure_months,
                        },
                    )
                )
                deviation = (
                    abs(employment_result.verified_annual_income - declared_annual_income)
                    / declared_annual_income
                )
                matched = employment_result.is_employment_confirmed and deviation <= (
                    _INCOME_DEVIATION_THRESHOLD
                )
                checks.append(
                    VerificationCheck(
                        source_system=SourceSystem.MOCK_EMPLOYER,
                        checked_fact_type=FactType.EMPLOYER_NAME.value,
                        declared_value=f"{employer_name.value}, ${declared_annual_income}/yr",
                        external_value=(
                            f"confirmed={employment_result.is_employment_confirmed} "
                            f"verified_income=${employment_result.verified_annual_income}"
                        ),
                        verdict=(
                            VerificationVerdict.MATCHED
                            if matched
                            else VerificationVerdict.CONTRADICTED
                        ),
                        confidence=max(0.0, 1.0 - min(deviation, 1.0)),
                        detail=f"tenure {employment_result.tenure_months} months",
                    )
                )
            else:
                checks.append(
                    VerificationCheck(
                        source_system=SourceSystem.MOCK_EMPLOYER,
                        checked_fact_type=FactType.EMPLOYER_NAME.value,
                        declared_value=None,
                        external_value=None,
                        verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                        confidence=0.0,
                        detail="pay-stub facts (employer / income) were not extracted",
                    )
                )

            if synthetic_id is not None:
                credit_report = await self._bureau_client.get_credit_report(
                    given_name=applicant.given_name,
                    family_name=applicant.family_name,
                    date_of_birth=applicant.date_of_birth,
                    synthetic_id=synthetic_id.normalized_value,
                )
                snapshots.append(
                    ExternalResponseSnapshot(
                        source_system=SourceSystem.MOCK_BUREAU,
                        response_payload={
                            "credit_score": credit_report.credit_score,
                            "hard_inquiries_last_12_months": (
                                credit_report.hard_inquiries_last_12_months
                            ),
                            "is_duplicate_identity_flag": credit_report.is_duplicate_identity_flag,
                            "tradeline_count": len(credit_report.tradelines),
                        },
                    )
                )

            if synthetic_id is not None and declared_annual_income:
                transaction_history = await self._core_banking_client.get_transaction_history(
                    given_name=applicant.given_name,
                    family_name=applicant.family_name,
                    synthetic_id=synthetic_id.normalized_value,
                    declared_annual_income=declared_annual_income,
                )
                snapshots.append(
                    ExternalResponseSnapshot(
                        source_system=SourceSystem.MOCK_CORE_BANKING,
                        response_payload={
                            "average_daily_balance_cents": (
                                transaction_history.average_daily_balance_cents
                            ),
                            "nsf_count_last_90_days": transaction_history.nsf_count_last_90_days,
                        },
                    )
                )

            run_id = self._id_generator.new_id()
            check_ids = [self._id_generator.new_id() for _ in checks]
            snapshot_ids = [self._id_generator.new_id() for _ in snapshots]
            await uow.verification.add_run(
                run_id=run_id,
                tenant_id=command.tenant_id,
                application_id=command.application_id,
                checks=checks,
                check_ids=check_ids,
                snapshots=snapshots,
                snapshot_ids=snapshot_ids,
                completed_at=self._clock.now(),
            )
            await uow.commit()

            contradiction_count = sum(
                1 for check in checks if check.verdict is VerificationVerdict.CONTRADICTED
            )
            return VerifyApplicationFactsResult(
                checks=checks,
                contradiction_count=contradiction_count,
                summary=build_verification_summary(checks),
            )
