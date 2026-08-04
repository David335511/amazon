"""Retailer (Walmart / Home Depot) sourcing API routes.

Design decisions:
- Thin route handlers that delegate to the shared RetailerService, feeding the
  same sourcing methodology used by the rest of the platform.
- Lookups respect the monthly SerpApi budget (enforced inside the client); the
  budget and scheduler status are exposed for observability.
- Errors map to consistent HTTP status codes: budget exhausted -> 429,
  bad/missing key -> 401, upstream failure -> 502.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.integrations.retailers import (
    RetailerAuthenticationError,
    RetailerBudgetExceededError,
    RetailerConfig,
    RetailerRequestError,
    RetailerService,
    build_retailer_service,
)
from app.integrations.retailers import (
    get_retailer_budget as get_shared_budget,
)
from app.integrations.retailers import (
    get_retailer_job as get_shared_job,
)
from app.integrations.retailers import (
    get_retailer_service as get_shared_service,
)
from app.integrations.retailers.models import (
    RetailerLookupRequest,
    RetailerProduct,
    RetailerProvider,
)
from app.sourcing.models import OpportunityScore

logger = get_logger(__name__)

router = APIRouter(prefix="/sourcing/retailers", tags=["sourcing-retailers"])


# ── Request / Response Models ────────────────────────────────


class RetailerLookupRequestModel(BaseModel):
    """Parameters for a retailer product lookup."""

    provider: RetailerProvider = Field(..., description="Retailer to query")
    product_id: str = Field(..., min_length=1, description="Retailer item number / product id")
    amazon_price: Decimal | None = Field(
        None,
        gt=0,
        description="Expected Amazon selling price (drives profit/ROI scoring)",
    )
    fba_fulfillment_fee: Decimal = Field(
        Decimal("0"),
        ge=0,
        description="Per-unit FBA fulfillment fee",
    )
    referral_fee_percent: Decimal | None = Field(
        None,
        ge=0,
        le=100,
        description="Amazon referral fee percentage (e.g. 15.00)",
    )


class RetailerProductSummary(BaseModel):
    """A trimmed, API-safe view of a retailer product (no raw payload)."""

    provider: RetailerProvider
    product_id: str
    title: str | None
    brand: str | None
    model_number: str | None
    upc: str | None
    url: str | None
    image: str | None
    current_price: Decimal | None
    original_price: Decimal | None
    currency: str
    rating: Decimal | None
    review_count: int | None
    seller_count: int | None
    in_stock: bool | None
    availability: str | None


class RetailerLookupResponse(BaseModel):
    """A retailer product and its sourcing score."""

    product: RetailerProductSummary
    opportunity: OpportunityScore


def _summarize(product: RetailerProduct) -> RetailerProductSummary:
    return RetailerProductSummary(
        provider=product.provider,
        product_id=product.product_id,
        title=product.title,
        brand=product.brand,
        model_number=product.model_number,
        upc=product.upc,
        url=product.url,
        image=product.image,
        current_price=product.price.current,
        original_price=product.price.original,
        currency=product.price.currency,
        rating=product.rating.rating,
        review_count=product.rating.review_count,
        seller_count=product.seller_count,
        in_stock=product.in_stock,
        availability=product.availability,
    )


# ── Dependency ───────────────────────────────────────────────


async def get_retailer_service() -> RetailerService:
    """Yield the shared RetailerService, falling back to a fresh one in tests."""
    service = get_shared_service()
    if service is None:
        service = build_retailer_service()
    return service


# ═══════════════════════════════════════════════════════════════
# Lookup Endpoint
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/lookup",
    response_model=RetailerLookupResponse,
    summary="Look up and score a retailer product",
    description=(
        "Fetches a product from Walmart or Home Depot (via SerpApi) and scores "
        "it with the sourcing methodology. Provide an Amazon sell price to get "
        "meaningful profit/ROI rule results. Respects the monthly SerpApi budget."
    ),
)
async def lookup_retailer_product(
    body: RetailerLookupRequestModel,
    service: RetailerService = Depends(get_retailer_service),
) -> RetailerLookupResponse:
    """Fetch and score a single retailer product."""
    try:
        product, score = await service.fetch_and_score(
            RetailerLookupRequest(provider=body.provider, product_id=body.product_id),
            amazon_price=body.amazon_price,
            fba_fulfillment_fee=body.fba_fulfillment_fee,
            referral_fee_percent=body.referral_fee_percent,
        )
    except RetailerAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"SerpApi authentication failed: {exc}",
        ) from exc
    except RetailerBudgetExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except RetailerRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Retailer lookup failed: {exc}",
        ) from exc

    return RetailerLookupResponse(product=_summarize(product), opportunity=score)


# ═══════════════════════════════════════════════════════════════
# Observability Endpoints
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/budget",
    summary="Get monthly SerpApi budget usage",
    description=(
        "Returns how many SerpApi searches have been used this month, how many "
        "remain, and today's recommended daily allowance for pacing."
    ),
)
async def get_budget_status() -> dict[str, object]:
    """Return current monthly budget usage for retailer lookups."""
    budget = get_shared_budget()
    if budget is None:
        return {
            "configured": False,
            "monthly_limit": 0,
            "used": 0,
            "remaining": 0,
            "daily_allowance": 0,
        }
    used = await budget.used_this_month()
    remaining = await budget.remaining()
    allowance = await budget.daily_allowance()
    return {
        "configured": True,
        "monthly_limit": budget.monthly_limit,
        "used": used,
        "remaining": remaining,
        "daily_allowance": allowance,
    }


@router.get(
    "/status",
    summary="Get retailer integration status",
    description=(
        "Reports whether SerpApi is configured and whether the background "
        "refresh scheduler is running."
    ),
)
async def get_status() -> dict[str, object]:
    """Return the retailer integration runtime status."""
    job = get_shared_job()
    budget = get_shared_budget()
    return {
        "serpapi_configured": RetailerConfig().is_configured,
        "scheduler_running": job is not None,
        "monthly_budget": budget.monthly_limit if budget is not None else 0,
        "interval_seconds": getattr(job, "_interval", None) if job is not None else None,
    }
