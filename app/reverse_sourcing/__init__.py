"""Reverse sourcing engine.

Turns an Amazon ASIN into a full supplier analysis. For a given ASIN it returns:

- **every known supplier** that carries the product, with current price,
  shipping cost, landed cost, availability, MOQ and current discount;
- **historical supplier prices & discounts** (derived from past runs);
- a **predicted future discount** per supplier;
- a **supplier ranking** and the **best / cheapest / fastest /
  highest-confidence** suppliers;
- **sourcing recommendations** and a summary.

It is fully provider-driven and plug-in friendly: the engine talks ONLY to a
`SupplierProvider` (which adapts the existing `PluginManager`), so **adding a
supplier plugin is just adding a file to ``app/plugins/suppliers/`` — the
engine never changes.** The ASIN resolver, discount predictor and supplier
intelligence are all pluggable seams.
"""

from app.reverse_sourcing.config import ReverseSourcingConfig
from app.reverse_sourcing.errors import (
    ReverseSourcingError,
    ReverseSourcingNotFoundError,
    ReverseSourcingValidationError,
)
from app.reverse_sourcing.manager import ReverseSourcingManager
from app.reverse_sourcing.models import ReverseSourcingOffer, ReverseSourcingRun
from app.reverse_sourcing.predictor import DiscountPredictor, TrendDiscountPredictor
from app.reverse_sourcing.provider import PluginManagerProvider, SupplierProvider
from app.reverse_sourcing.repository import ReverseSourcingRepository
from app.reverse_sourcing.resolver import AsinResolver, PassthroughAsinResolver
from app.reverse_sourcing.schemas import (
    HistoricalSupplierRead,
    RankedSupplierRead,
    ReverseSourcingCapabilities,
    ReverseSourcingList,
    ReverseSourcingRead,
    ReverseSourcingRequest,
    ReverseSourcingRunRead,
    ReverseSourcingStats,
    SupplierHighlightRead,
    SupplierOfferRead,
)

__all__ = [
    "AsinResolver",
    "DiscountPredictor",
    "HistoricalSupplierRead",
    "PassthroughAsinResolver",
    "PluginManagerProvider",
    "RankedSupplierRead",
    "ReverseSourcingCapabilities",
    "ReverseSourcingConfig",
    "ReverseSourcingError",
    "ReverseSourcingList",
    "ReverseSourcingManager",
    "ReverseSourcingNotFoundError",
    "ReverseSourcingOffer",
    "ReverseSourcingRead",
    "ReverseSourcingRepository",
    "ReverseSourcingRequest",
    "ReverseSourcingRun",
    "ReverseSourcingRunRead",
    "ReverseSourcingStats",
    "ReverseSourcingValidationError",
    "SupplierHighlightRead",
    "SupplierOfferRead",
    "SupplierProvider",
    "TrendDiscountPredictor",
]
