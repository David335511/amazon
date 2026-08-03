"""Lineage for computed feature values.

Every stored feature value records how it was produced: the feature version
(the exact formula code), when it was computed, the input signals used (with
their sources and versions), and a hash of the output value. This makes any
downstream decision — sourcing, pricing, buy-box — auditable and reproducible.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.features.signals import SignalInfo


def hash_value(value: Any) -> str:
    """Canonical short hash of a JSON value for auditability."""
    blob = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_lineage(
    *,
    feature_key: str,
    method: str,
    version: str,
    computed_at: datetime,
    value: Any,
    used_signals: dict[str, SignalInfo] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Build a lineage record for a computed feature value."""
    inputs: list[dict[str, Any]] = []
    for key, info in (used_signals or {}).items():
        inputs.append(
            {
                "key": key,
                "value": info.value,
                "source": info.source,
                "version": info.version,
            }
        )
    record: dict[str, Any] = {
        "feature": feature_key,
        "method": method,
        "version": version,
        "computed_at": computed_at.isoformat(),
        "output_hash": hash_value(value),
        "inputs": inputs,
    }
    if notes:
        record["notes"] = notes
    return record
