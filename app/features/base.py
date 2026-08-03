"""Core abstractions for feature computers.

A `FeatureComputer` is the unit of feature engineering: it declares the feature
key, a human-readable formula/method, a semantic version, the output value type,
the input signals it requires, and an optional refresh TTL. Its ``compute``
method turns a `SignalBundle` into a `FeatureComputeResult` (value + confidence
+ the exact signals used).

Because the computer declares its version and which signals it used, every
stored value is reproducible and auditable. Adding a new feature — including a
future ML model — is just registering a new `FeatureComputer`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.features.models import FeatureValueType
from app.features.signals import SignalBundle, SignalInfo


class EntityContext(BaseModel):
    """Identifies what entity a feature is being computed for.

    ``entity_type`` is the kind of thing (e.g. ``product``, ``sku``,
    ``supplier``, ``buy_box``); ``entity_id`` is its identifier (e.g. an ASIN or
    supplier UUID). ``user_id`` scopes owner-less data (None = platform-global).
    """

    entity_type: str
    entity_id: str
    user_id: str | None = None


class FeatureComputeResult(BaseModel):
    """The output of a `FeatureComputer.compute`.

    ``value`` may be any JSON-serializable scalar/list. ``confidence`` (0..1)
    reflects how many required signals were really present (fewer signals ->
    lower confidence). ``used_signals`` records the exact signal values consumed
    so lineage can be reconstructed.
    """

    value: Any
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    used_signals: dict[str, SignalInfo] = Field(default_factory=dict)
    notes: str | None = None


class FeatureComputer(ABC):
    """Base class for all feature computations.

    Subclasses override the class metadata and implement ``compute``. They are
    auto-discovered by the registry.
    """

    key: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    formula: ClassVar[str] = ""  # human-readable method
    version: ClassVar[str] = "1.0.0"  # bump when the formula changes
    value_type: ClassVar[FeatureValueType] = FeatureValueType.NUMERIC
    required_signals: ClassVar[tuple[str, ...]] = ()
    ttl_seconds: ClassVar[int | None] = None  # None -> use FeatureConfig default

    @abstractmethod
    async def compute(self, entity: EntityContext, signals: SignalBundle) -> FeatureComputeResult:
        """Compute the feature for an entity from its signals."""
