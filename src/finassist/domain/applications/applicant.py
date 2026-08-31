"""The `Applicant` entity.

Modeled as data owned by an `Application`'s creation, not as its own aggregate with a repository
-- see docs/adr/0009 decision 5 for why (identity resolution across applications is a Phase 4
concern; giving it a repository now would be a premature abstraction with no caller).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from finassist.domain.shared.identifiers import ApplicantId, TenantId


@dataclass(frozen=True, slots=True)
class Applicant:
    applicant_id: ApplicantId
    tenant_id: TenantId
    given_name: str
    family_name: str
    date_of_birth: date
    email: str

    def __post_init__(self) -> None:
        if not self.given_name.strip():
            raise ValueError("applicant given_name must not be blank")
        if not self.family_name.strip():
            raise ValueError("applicant family_name must not be blank")
        if "@" not in self.email:
            raise ValueError(f"applicant email {self.email!r} is not a valid address")
