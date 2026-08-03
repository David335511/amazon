"""Reasoning trace — the auditable record of one agent's deliberation.

Every agent appends traces as it works (`context.trace(...)`). Traces capture
the step name, free-text detail and structured data so that a supervisor (or a
human) can replay *why* an agent reached a decision. They are persisted with the
run and exposed over the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ReasoningTrace:
    """One recorded reasoning step."""

    step: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "detail": self.detail,
            "data": self.data,
            "timestamp": self.timestamp,
        }
