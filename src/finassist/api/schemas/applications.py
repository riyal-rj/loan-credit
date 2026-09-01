"""Pydantic request/response models for `finassist.api.routes.applications` (Phase 3).

Master instruction §23: "Use Pydantic models at external boundaries and domain types internally."
Every route converts to/from these at the edge; domain types (`Money`, `TenantId`, ...) never
appear in a request/response body directly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateApplicationRequest(BaseModel):
    applicant_given_name: str = Field(min_length=1)
    applicant_family_name: str = Field(min_length=1)
    applicant_date_of_birth: date
    applicant_email: str = Field(min_length=3)
    product_id: str
    requested_amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    requested_term_months: int = Field(ge=1)


class CreateApplicationResponse(BaseModel):
    application_id: str
    applicant_id: str
    status: str
    version: int


class SubmitApplicationResponse(BaseModel):
    application_id: str
    status: str
    version: int
    workflow_id: str | None


class ResubmitApplicationResponse(BaseModel):
    application_id: str
    status: str
    version: int
    workflow_id: str | None


class UploadDocumentResponse(BaseModel):
    document_id: str
    application_id: str
    object_key: str
    checksum_sha256: str


class ApplicationStatusResponse(BaseModel):
    application_id: str
    status: str
    version: int
    active_workflow_id: str | None


class ReviewDecisionRequest(BaseModel):
    decision: str = Field(description="APPROVED | DECLINED | NEEDS_MORE_INFORMATION | ESCALATED")
    reason: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)


class ReviewDecisionResponse(BaseModel):
    application_id: str
    workflow_id: str
    decision: str


class ExtractedFactResponse(BaseModel):
    fact_id: str
    document_id: str
    fact_type: str
    value: str
    normalized_value: str
    confidence: float
    page: int
    extraction_method: str
    extractor_version: str


class VerificationCheckResponse(BaseModel):
    source_system: str
    checked_fact_type: str
    declared_value: str | None
    external_value: str | None
    verdict: str
    confidence: float
    detail: str


class ApplicationEvidenceResponse(BaseModel):
    application_id: str
    facts: list[ExtractedFactResponse]
    verification_checks: list[VerificationCheckResponse]
