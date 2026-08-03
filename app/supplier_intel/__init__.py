"""Supplier intelligence.

Tracks the **historical** behaviour of suppliers (prices, sale frequency,
coupon frequency, inventory stability, shipping speed, return policy, customer
service, order-cancellation rate, discount patterns, stockout frequency) and
computes five scores purely from that history:

- **Supplier Reliability Score** — how dependable the supplier is.
- **Supplier Volatility Score** — how unstable its behaviour is.
- **Supplier Discount Score** — how favourable its discount behaviour is.
- **Supplier Risk Score** — overall downside / concentration of risk.
- **Supplier Seasonality Score** — how seasonal / periodic its pricing is.

Every profile also returns an **AI explanation** of supplier behaviour — a
deterministic reasoning narrative over the historical scores and metrics (a
seam for real LLM providers).

Everything is historical: each `SupplierObservation` is one period snapshot and
scores are computed on demand over the full stored series, so they never go
stale and always reflect the complete record.
"""

from app.supplier_intel.base import TRACKED_METRICS, SupplierScore
from app.supplier_intel.config import SupplierIntelConfig
from app.supplier_intel.errors import (
    SupplierIntelError,
    SupplierIntelNotFoundError,
    SupplierIntelValidationError,
)
from app.supplier_intel.manager import SupplierIntelManager
from app.supplier_intel.models import SupplierObservation
from app.supplier_intel.repository import SupplierIntelRepository
from app.supplier_intel.schemas import (
    ObservationCreate,
    ObservationList,
    ObservationRead,
    ScoreRead,
    SupplierIntelBatchRequest,
    SupplierIntelCapabilities,
    SupplierIntelRead,
    SupplierIntelStats,
)
from app.supplier_intel.scoring import compute_scores, explain, summarize

__all__ = [
    "TRACKED_METRICS",
    "ObservationCreate",
    "ObservationList",
    "ObservationRead",
    "ScoreRead",
    "SupplierIntelBatchRequest",
    "SupplierIntelCapabilities",
    "SupplierIntelConfig",
    "SupplierIntelError",
    "SupplierIntelManager",
    "SupplierIntelNotFoundError",
    "SupplierIntelRead",
    "SupplierIntelRepository",
    "SupplierIntelStats",
    "SupplierIntelValidationError",
    "SupplierObservation",
    "SupplierScore",
    "compute_scores",
    "explain",
    "summarize",
]
