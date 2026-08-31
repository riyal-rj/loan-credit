"""The scenario catalog: the single source of truth for "what kind of synthetic case is this."

Every mock service and generator function takes a `scenario_id` and looks up behavior here --
never hard-codes scenario-specific logic inline. A scenario controls both the *data* a generator
produces (e.g. a thin bureau file) and, for services, an optional *fault* to inject instead of a
normal response (master instruction §6.1: "mock ... services with deterministic scenario
behavior"; §2: "deterministic fault injection").

This is a foundational subset for Phase 2. Phase 9's evaluation golden dataset (§21.2) extends
this catalog with additional scenarios (contradictory documents, prompt-injection payloads,
protected-cohort cases) once the phases that consume them exist -- adding a scenario here without
a consumer would be exactly the premature, untested addition the coding standards warn against.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FaultBehavior(StrEnum):
    """A fault a mock service should inject instead of its normal response."""

    NONE = "none"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    MALFORMED_RESPONSE = "malformed_response"
    RATE_LIMITED = "rate_limited"


class ScenarioCategory(StrEnum):
    DATA = "data"
    FAULT = "fault"


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    description: str
    category: ScenarioCategory
    fault: FaultBehavior = FaultBehavior.NONE


_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        scenario_id="NORMAL_ELIGIBLE",
        description="Clean applicant: good bureau score, verified employment, healthy cash flow.",
        category=ScenarioCategory.DATA,
    ),
    Scenario(
        scenario_id="THIN_FILE_BUREAU",
        description="Bureau has minimal credit history (few tradelines, short history length).",
        category=ScenarioCategory.DATA,
    ),
    Scenario(
        scenario_id="KYC_IDENTITY_MISMATCH",
        description="KYC check fails: submitted identity does not match the verification source.",
        category=ScenarioCategory.DATA,
    ),
    Scenario(
        scenario_id="EMPLOYER_VERIFICATION_MISMATCH",
        description="Employer confirms a different income/tenure than the applicant declared.",
        category=ScenarioCategory.DATA,
    ),
    Scenario(
        scenario_id="DUPLICATE_IDENTITY",
        description="Bureau/KYC flag this identity as already associated with another case.",
        category=ScenarioCategory.DATA,
    ),
    Scenario(
        scenario_id="LOW_BALANCE_NSF",
        description="Transaction history shows a low average balance and repeated NSF events.",
        category=ScenarioCategory.DATA,
    ),
    Scenario(
        scenario_id="BUREAU_SERVICE_TIMEOUT",
        description="The bureau service does not respond within a reasonable time.",
        category=ScenarioCategory.FAULT,
        fault=FaultBehavior.TIMEOUT,
    ),
    Scenario(
        scenario_id="KYC_SERVICE_ERROR",
        description="The KYC service returns an unexpected server error.",
        category=ScenarioCategory.FAULT,
        fault=FaultBehavior.SERVER_ERROR,
    ),
    Scenario(
        scenario_id="EMPLOYER_SERVICE_MALFORMED",
        description="The employer verification service returns a malformed/invalid response body.",
        category=ScenarioCategory.FAULT,
        fault=FaultBehavior.MALFORMED_RESPONSE,
    ),
    Scenario(
        scenario_id="CORE_BANKING_RATE_LIMITED",
        description="The core-banking service rejects the request with a rate-limit error.",
        category=ScenarioCategory.FAULT,
        fault=FaultBehavior.RATE_LIMITED,
    ),
)

SCENARIO_CATALOG: dict[str, Scenario] = {s.scenario_id: s for s in _SCENARIOS}

DEFAULT_SCENARIO_ID = "NORMAL_ELIGIBLE"


class UnknownScenarioError(KeyError):
    def __init__(self, scenario_id: str) -> None:
        super().__init__(
            f"unknown scenario_id {scenario_id!r}; known scenarios: " f"{sorted(SCENARIO_CATALOG)}"
        )
        self.scenario_id = scenario_id


def get_scenario(scenario_id: str | None) -> Scenario:
    """Resolve `scenario_id` to a `Scenario`, defaulting to `NORMAL_ELIGIBLE` when omitted."""
    resolved_id = scenario_id or DEFAULT_SCENARIO_ID
    try:
        return SCENARIO_CATALOG[resolved_id]
    except KeyError as exc:
        raise UnknownScenarioError(resolved_id) from exc
