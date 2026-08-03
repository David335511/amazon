"""ORM model for the feature engineering platform.

The `feature_values` table is the feature store: one row per
(feature_key, entity_type, entity_id), holding the *current* computed value
plus its full audit trail. Compute-once-and-reuse means the latest value is
served until it goes stale; `refresh` recomputes and overwrites the row.

Design decisions:
- **Own table**, separate from product/order data, mirroring the documents and
  memory subsystems.
- **JSON `value_json`** holds the canonical value (works for numeric,
  categorical, boolean and vector features) while `numeric_value` denormalizes
  numeric features so they can be ranged/aggregated in SQL.
- **`version`** is the semantic version of the computing function (bump when
  the formula changes).
- **`lineage_json`** records method, inputs (with source/version) and an output
  hash — full reproducibility.
- **`stale_after`** = computed_at + ttl; the manager refreshes past this.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class FeatureValueType(StrEnum):
    """The kind of value a feature computes."""

    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    VECTOR = "vector"


class FeatureValue(Base, UUIDMixin, TimestampMixin):
    """A single stored (current) computed feature value for an entity."""

    __tablename__ = "feature_values"
    __table_args__ = (
        UniqueConstraint(
            "feature_key",
            "entity_type",
            "entity_id",
            name="uq_feature_values_entity",
        ),
    )

    feature_key: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
        comment="Canonical feature key (e.g. price_stability_score)",
    )
    entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="Kind of entity (product, sku, supplier, buy_box, ...)",
    )
    entity_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
        comment="Entity identifier (ASIN, SKU, supplier UUID, ...)",
    )

    value_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FeatureValueType.NUMERIC.value,
    )
    # Denormalized numeric value for ranged/aggregated queries (numeric features).
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Canonical JSON-serialized value (all feature types).
    value_json: Mapped[str] = mapped_column(Text, nullable=False)

    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5,
        comment="0..1 confidence given signal availability",
    )
    version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1.0.0",
        comment="Semantic version of the computing function",
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="When this value was computed",
    )
    stale_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="computed_at + ttl; the value should be refreshed past this",
    )
    lineage_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON lineage (method, inputs, output hash)",
    )

    def __repr__(self) -> str:
        return f"<FeatureValue({self.feature_key}, {self.entity_type}/{self.entity_id}, v{self.version})>"
