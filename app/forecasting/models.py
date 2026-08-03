"""ORM models for the forecasting platform.

Two tables:

- ``forecasts`` — one row per stored forecast: the point prediction, the 95%
  confidence interval, confidence, model (name/method/version), the ensemble
  members used, a human-readable explanation, a snapshot of the input series /
  features / metadata (full reproducibility), and the forecast's `as_of`.
- ``forecast_actuals`` — realized outcomes linked to a forecast, used to compute
  **historical accuracy** (MAE / MAPE / RMSE / bias) per model and target.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class Forecast(Base, UUIDMixin, TimestampMixin):
    """A single stored forecast."""

    __tablename__ = "forecasts"

    target: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
        comment="ForecastTarget value (price, roi, profit, inventory, sales, buy_box, competition)",
    )
    entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="Kind of entity (product, sku, supplier, ...)",
    )
    entity_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
        comment="Entity identifier (ASIN, SKU, supplier UUID, ...)",
    )
    horizon: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Number of future periods forecast ahead",
    )

    model_name: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True,
        comment="Which ForecastModel produced this forecast",
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")

    prediction: Mapped[float] = mapped_column(Float, nullable=False)
    lower: Mapped[float] = mapped_column(Float, nullable=False)
    upper: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    used_models_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]",
        comment="JSON list of member model names (ensembles)",
    )
    series_json: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="JSON snapshot of the input series (reproducibility)",
    )
    features_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    frequency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="End of the historical series / the period the forecast starts from",
    )

    def __repr__(self) -> str:
        return f"<Forecast({self.model_name}, {self.target}, {self.entity_id}, h={self.horizon})>"


class ForecastActual(Base, UUIDMixin, TimestampMixin):
    """A realized outcome, linked to the forecast that predicted it."""

    __tablename__ = "forecast_actuals"

    forecast_id: Mapped[UUID] = mapped_column(
        ForeignKey("forecasts.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    model_name: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True,
        comment="Denormalized model name (for accuracy stats without a join)",
    )
    target: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
        comment="Denormalized target for accuracy stats",
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="The period the actual belongs to",
    )
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:
        return f"<ForecastActual({self.model_name}, {self.target}, actual={self.actual_value})>"
