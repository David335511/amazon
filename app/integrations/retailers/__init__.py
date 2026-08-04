"""Retailer product data integration (Walmart / Home Depot).

Provides a free-tier-friendly client (SerpApi) for looking up product data
from retailers that do not offer their own public product API (Home Depot) or
gate their APIs behind seller/supplier onboarding (Walmart).

The normalized ``RetailerProduct`` and the ``RetailerService`` mapping/scoring
helpers feed the existing sourcing methodology, so a single retailer lookup can
be scored with the same 7-rule methodology used for database-backed products.
"""

from app.integrations.retailers.budget import RetailerBudget
from app.integrations.retailers.client import (
    RetailerAuthenticationError,
    RetailerBudgetExceededError,
    RetailerCache,
    RetailerError,
    RetailerRateLimiter,
    RetailerRateLimitError,
    RetailerRequestError,
    SerpApiClient,
)
from app.integrations.retailers.config import RetailerConfig
from app.integrations.retailers.lifecycle import (
    configure_retailer_runtime,
    get_retailer_budget,
    get_retailer_job,
    get_retailer_service,
    shutdown_retailer_runtime,
)
from app.integrations.retailers.models import (
    RetailerLookupRequest,
    RetailerPrice,
    RetailerProduct,
    RetailerProvider,
    RetailerRating,
)
from app.integrations.retailers.providers import HomeDepotProvider, WalmartProvider
from app.integrations.retailers.scheduler import RetailerRefreshJob
from app.integrations.retailers.service import (
    RetailerService,
    build_retailer_service,
    parse_monitor_products,
)

__all__ = [
    "HomeDepotProvider",
    "RetailerAuthenticationError",
    "RetailerBudget",
    "RetailerBudgetExceededError",
    "RetailerCache",
    "RetailerConfig",
    "RetailerError",
    "RetailerLookupRequest",
    "RetailerPrice",
    "RetailerProduct",
    "RetailerProvider",
    "RetailerRateLimitError",
    "RetailerRateLimiter",
    "RetailerRating",
    "RetailerRefreshJob",
    "RetailerRequestError",
    "RetailerService",
    "SerpApiClient",
    "WalmartProvider",
    "build_retailer_service",
    "configure_retailer_runtime",
    "get_retailer_budget",
    "get_retailer_job",
    "get_retailer_service",
    "parse_monitor_products",
    "shutdown_retailer_runtime",
]
