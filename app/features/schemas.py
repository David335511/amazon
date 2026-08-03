"""Pydantic schemas for the feature engineering API.

`FeatureValueRead` mirrors a stored row with the `value` surfaced as its natural
JSON type (not the stored string), plus a resolved `feature_name`. Definitions
are returned from the registry (code), not the database, so the API doubles as
living documentation of every feature's method, version and required signals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.features.models import FeatureValueType


class FeatureDefinitionRead(BaseModel):
    """Metadata for a registered feature (from code, not DB)."""

    key: str
    name: str
    description: str
    formula: str
    version: str
    value_type: FeatureValueType
    required_signals: list[str]
    ttl_seconds: int | None


class FeatureValueRead(BaseModel):
    """A stored (or just-computed) feature value."""

    id: UUID
    feature_key: str
    feature_name: str
    entity_type: str
    entity_id: str
    value_type: FeatureValueType
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    version: str
    computed_at: datetime
    stale_after: datetime | None
    ttl_seconds: int | None
    lineage: dict[str, Any] = Field(default_factory=dict)


class FeatureCalculateRequest(BaseModel):
    """Request to calculate (or return fresh) a single feature value."""

    feature_key: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    force: bool = False  # bypass the store and recompute
    # Optional raw signal overrides, keyed by signal name. When provided they
    # are merged over whatever the SignalProvider returns.
    signals: dict[str, Any] = Field(default_factory=dict)


class FeatureBatchItem(BaseModel):
    """One item in a batch calculation request."""

    feature_key: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)


class FeatureBatchRequest(BaseModel):
    """Request to calculate several feature values in one call."""

    requests: list[FeatureBatchItem] = Field(min_length=1)
    force: bool = False
    signals: dict[str, Any] = Field(default_factory=dict)


class FeatureValueList(BaseModel):
    """Paginated list of stored feature values."""

    items: list[FeatureValueRead]
    total: int


class FeatureStats(BaseModel):
    """Aggregate statistics over the stored feature store."""

    total_values: int = 0
    by_feature: dict[str, int] = Field(default_factory=dict)
    stale_values: int = 0


class FeatureCapabilities(BaseModel):
    """Which features / providers this deployment supports."""

    enabled: bool
    feature_count: int
    features: list[FeatureDefinitionRead]
    signal_provider: str
    default_ttl_seconds: int
