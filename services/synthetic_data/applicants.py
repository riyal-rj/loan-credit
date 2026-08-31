"""Synthetic applicant generation.

`SyntheticApplicant` is the seed record every other generator (bureau, KYC, employer,
transactions, documents) is derived from -- they all take an applicant plus a scenario, never
invent identity fields independently, so a bureau report and a KYC result generated for the same
applicant+scenario are always internally consistent (same name, same synthetic ID).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

from services.synthetic_data.rng import rng_for

_GIVEN_NAMES = (
    "Ada",
    "Grace",
    "Alan",
    "Katherine",
    "Edsger",
    "Margaret",
    "Claude",
    "Barbara",
    "Donald",
    "Radia",
)
_FAMILY_NAMES = (
    "Lovelace",
    "Hopper",
    "Turing",
    "Johnson",
    "Dijkstra",
    "Hamilton",
    "Shannon",
    "Liskov",
    "Knuth",
    "Perlman",
)
_STREET_NAMES = ("Maple", "Oak", "Cedar", "Birch", "Elm", "Pine", "Willow", "Aspen")
_CITIES = ("Springfield", "Fairview", "Riverside", "Georgetown", "Clinton")
_EMPLOYERS = (
    "Northwind Traders Inc.",
    "Contoso Logistics LLC",
    "Fabrikam Manufacturing",
    "Globex Retail Group",
    "Initech Software",
)


def _synthetic_ssn(rng: random.Random) -> str:
    # "900-xx-xxxx" is not a valid real SSN range (900+ area numbers were never issued), so this
    # can never collide with or be mistaken for a real identity.
    return f"900-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"


@dataclass(frozen=True, slots=True)
class SyntheticApplicant:
    synthetic_id: str
    """Deterministic, scenario-scoped identifier -- distinct from any real-looking ID; always
    prefixed so it can never be mistaken for a real SSN (master instruction §4: no real customer
    identity)."""

    given_name: str
    family_name: str
    date_of_birth: date
    email: str
    street_address: str
    city: str
    employer_name: str
    declared_annual_income: int


def generate_applicant(scenario_id: str, index: int = 0) -> SyntheticApplicant:
    rng = rng_for(scenario_id, index)
    given_name = rng.choice(_GIVEN_NAMES)
    family_name = rng.choice(_FAMILY_NAMES)
    birth_year = rng.randint(1965, 2002)
    birth_month = rng.randint(1, 12)
    birth_day = rng.randint(1, 28)
    street_number = rng.randint(100, 9999)

    return SyntheticApplicant(
        synthetic_id=_synthetic_ssn(rng),
        given_name=given_name,
        family_name=family_name,
        date_of_birth=date(birth_year, birth_month, birth_day),
        email=f"{given_name.lower()}.{family_name.lower()}.{index}@synthetic.test",
        street_address=f"{street_number} {rng.choice(_STREET_NAMES)} St",
        city=rng.choice(_CITIES),
        employer_name=rng.choice(_EMPLOYERS),
        declared_annual_income=rng.randint(35_000, 145_000),
    )
