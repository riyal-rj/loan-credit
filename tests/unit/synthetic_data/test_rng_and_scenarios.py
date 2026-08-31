from __future__ import annotations

import pytest
from services.synthetic_data.rng import derive_seed, rng_for
from services.synthetic_data.scenarios import (
    DEFAULT_SCENARIO_ID,
    SCENARIO_CATALOG,
    UnknownScenarioError,
    get_scenario,
)


def test_derive_seed_is_deterministic() -> None:
    assert derive_seed("NORMAL_ELIGIBLE", 0) == derive_seed("NORMAL_ELIGIBLE", 0)


def test_derive_seed_differs_by_scenario_and_index() -> None:
    seeds = {
        derive_seed("NORMAL_ELIGIBLE", 0),
        derive_seed("NORMAL_ELIGIBLE", 1),
        derive_seed("THIN_FILE_BUREAU", 0),
    }
    assert len(seeds) == 3


def test_rng_for_produces_identical_sequences_for_same_inputs() -> None:
    a = rng_for("NORMAL_ELIGIBLE", 0)
    b = rng_for("NORMAL_ELIGIBLE", 0)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_get_scenario_defaults_to_normal_eligible() -> None:
    assert get_scenario(None).scenario_id == DEFAULT_SCENARIO_ID


def test_get_scenario_raises_for_unknown_id() -> None:
    with pytest.raises(UnknownScenarioError):
        get_scenario("NOT_A_REAL_SCENARIO")


def test_every_catalog_entry_id_matches_its_key() -> None:
    for key, scenario in SCENARIO_CATALOG.items():
        assert key == scenario.scenario_id
