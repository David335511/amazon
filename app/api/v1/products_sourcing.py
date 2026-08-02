"""Product sourcing API routes — clean, versioned endpoints for product analytics.

Design decisions:
- Thin route handlers that delegate to the service layer.
- Consistent error responses with structured JSON.
- Pagination via query parameters with sensible defaults.
- Caching via the ResponseCache dependency.
- Async refresh for long-running Keepa API calls.
- All responses use DTOs (not ORM models).
"""

from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import ResponseCache
from app.core.database import get_db
from app.core.dependencies import get_product_service as get_commerce_product_service
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.schemas.product_sourcing import (
    BSRHistoryDTO,
    BatchRefreshResponse,
    BuyBoxDTO,
    ProductDetailDTO,
    ProductPricingDTO,
    ProductRefreshRequest,
    ProductSearchResponse,
    ProductSummaryDTO,
    RefreshResponse,
    SellerCountHistoryDTO,
)
from app.domain.services.product_sourcing_service import ProductSourcingService
from app.infrastructure.repositories.product_sourcing_repository import (
    ProductSourcingRepository,
)
from app.integrations.keepa.client import KeepaClient
from app.integrations.keepa.config import KeepaConfig
from app.integrations.keepa.repository import KeepaRepository

logger = get_logger(__name__)

router = APIRouter(prefix="/products", tags=["product-sourcing"])


# ── Dependency Injection ────────────────────────────────────


async def get_sourcing_service(
    db: AsyncSession = Depends(get_db),
    redis_client: object = Depends(get_redis),
) -> ProductSourcingService:
    """Create a ProductSourcingService with all dependencies."""
    repository = ProductSourcingRepository(db)

    # Configure Keepa client if API key is available
    keepa_config = KeepaConfig()
    keepa_client: KeepaClient | None = None
    keepa_repository: KeepaRepository | None = None

    if keepa_config.is_configured:
        keepa_client = KeepaClient(keepa_config, redis_client)  # type: ignore[arg-type]
        keepa_repository = KeepaRepository(db)

    cache = ResponseCache(redis_client)  # type: ignore[arg-type]

    return ProductSourcingService(
        repository=repository,
        keepa_client=keepa_client,
        keepa_repository=keepa_repository,
        cache=cache,
    )


# ── Search Endpoints ────────────────────────────────────────


@router.get(
    "/search/asin/{asin}",
    response_model=ProductDetailDTO | None,
    summary="Search product by ASIN",
    description="Look up a product by its Amazon ASIN. Checks database first, then falls back to Keepa API.",
)
async def search_by_asin(
    asin: str,
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> ProductDetailDTO | None:
    """Search for a product by its Amazon ASIN."""
    result = await service.search_by_asin(asin)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ASIN '{asin}' not found",
        )
    return result


@router.get(
    "/search/upc/{upc}",
    response_model=ProductDetailDTO | None,
    summary="Search product by UPC",
    description="Look up a product by its UPC barcode. Only checks the database.",
)
async def search_by_upc(
    upc: str,
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> ProductDetailDTO | None:
    """Search for a product by its UPC barcode."""
    result = await service.search_by_upc(upc)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with UPC '{upc}' not found",
        )
    return result


@router.get(
    "/search/title",
    response_model=ProductSearchResponse,
    summary="Search products by title",
    description="Search for products by title with pagination.",
)
async def search_by_title(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> ProductSearchResponse:
    """Search for products by title with pagination."""
    items, total = await service.search_by_title(q, page=page, page_size=page_size)
    return ProductSearchResponse(
        items=list(items),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
        query=q,
    )


# ── Product Detail Endpoints ────────────────────────────────


@router.get(
    "/{product_id}",
    response_model=ProductDetailDTO,
    summary="Get product details",
    description="Retrieve complete product details including pricing, reviews, and sales estimates.",
)
async def get_product_detail(
    product_id: UUID,
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> ProductDetailDTO:
    """Get complete product details by database ID."""
    result = await service.get_product_detail(product_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found",
        )
    return result


@router.get(
    "/{product_id}/pricing",
    response_model=ProductPricingDTO,
    summary="Get historical pricing",
    description="Retrieve historical Amazon and Buy Box pricing data.",
)
async def get_pricing_history(
    product_id: UUID,
    days: int = Query(default=90, ge=1, le=365, description="Days of history"),
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> ProductPricingDTO:
    """Get historical pricing data for a product."""
    result = await service.get_pricing_history(product_id, days=days)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found",
        )
    return result


@router.get(
    "/{product_id}/bsr",
    response_model=BSRHistoryDTO,
    summary="Get BSR history",
    description="Retrieve Best Sellers Rank history.",
)
async def get_bsr_history(
    product_id: UUID,
    days: int = Query(default=90, ge=1, le=365, description="Days of history"),
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> BSRHistoryDTO:
    """Get Best Sellers Rank history for a product."""
    result = await service.get_bsr_history(product_id, days=days)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found",
        )
    return result


@router.get(
    "/{product_id}/buy-box",
    response_model=BuyBoxDTO,
    summary="Get Buy Box history",
    description="Retrieve Buy Box price history and current winner.",
)
async def get_buy_box(
    product_id: UUID,
    days: int = Query(default=90, ge=1, le=365, description="Days of history"),
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> BuyBoxDTO:
    """Get Buy Box history for a product."""
    result = await service.get_buy_box(product_id, days=days)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found",
        )
    return result


@router.get(
    "/{product_id}/sellers",
    response_model=SellerCountHistoryDTO,
    summary="Get seller counts",
    description="Retrieve seller count history including new, used, and FBA sellers.",
)
async def get_seller_counts(
    product_id: UUID,
    days: int = Query(default=90, ge=1, le=365, description="Days of history"),
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> SellerCountHistoryDTO:
    """Get seller count history for a product."""
    result = await service.get_seller_counts(product_id, days=days)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found",
        )
    return result


# ── Refresh Endpoints ────────────────────────────────────────


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="Refresh product data",
    description="Trigger a refresh of product data from the Keepa API. Returns immediately with status.",
)
async def refresh_product(
    request: ProductRefreshRequest,
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> RefreshResponse:
    """Refresh product data from Keepa API."""
    return await service.refresh_product(request.asin, request.domain)


@router.post(
    "/refresh/batch",
    response_model=BatchRefreshResponse,
    summary="Batch refresh products",
    description="Refresh multiple products from the Keepa API.",
)
async def refresh_products_batch(
    asins: list[str] = Query(..., min_length=1, max_length=100, description="List of ASINs"),
    domain: str = Query(default="com", description="Amazon domain"),
    service: ProductSourcingService = Depends(get_sourcing_service),
) -> BatchRefreshResponse:
    """Refresh multiple products from Keepa API."""
    results: list[RefreshResponse] = []
    succeeded = 0
    failed = 0

    for asin in asins:
        result = await service.refresh_product(asin, domain)
        results.append(result)
        if result.status == "refresh_completed":
            succeeded += 1
        else:
            failed += 1

    return BatchRefreshResponse(
        total=len(asins),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )
