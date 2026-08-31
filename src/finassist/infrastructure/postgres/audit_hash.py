"""Audit hash-chain computation (docs/adr/0009 decision 2).

Pure function, no I/O -- kept separate from `unit_of_work.py` so the hashing rule itself can be
unit-tested without a database.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

GENESIS_HASH = "0" * 64


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_audit_hash(
    *,
    prev_hash: str,
    event_id: str,
    event_type: str,
    aggregate_id: str,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> str:
    """Return `sha256(prev_hash || canonical_json(rest))` as a hex digest.

    Deterministic given the same inputs, so a full-chain verification pass can recompute every
    hash from stored fields and compare, independent of when it runs.
    """
    material = _canonical_json(
        {
            "prev_hash": prev_hash,
            "event_id": event_id,
            "event_type": event_type,
            "aggregate_id": aggregate_id,
            "occurred_at": occurred_at.isoformat(),
            "payload": payload,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
