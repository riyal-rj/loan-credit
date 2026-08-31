"""Deterministic seeding for synthetic data generation.

Every generator in this package takes a `seed: int` (produced here) rather than reading from the
global `random` module, so two calls with the same scenario/index always produce byte-identical
output -- required for reproducible demo scenarios and evaluation datasets (master instruction
§21.2's golden datasets are only meaningful if they don't silently drift between runs).
"""

from __future__ import annotations

import hashlib
import random


def derive_seed(scenario_id: str, index: int) -> int:
    """Return a stable integer seed for `(scenario_id, index)`.

    Uses a hash rather than e.g. `hash()` because Python's built-in `hash()` for strings is
    salted per-process by default (`PYTHONHASHSEED`) and would break reproducibility across runs.
    """
    material = f"{scenario_id}:{index}".encode()
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:8], byteorder="big")


def rng_for(scenario_id: str, index: int) -> random.Random:
    """Return a `random.Random` seeded deterministically for `(scenario_id, index)`."""
    # Deterministic synthetic test-data generation, not a security/cryptographic use of randomness.
    return random.Random(derive_seed(scenario_id, index))  # noqa: S311 # nosec B311
