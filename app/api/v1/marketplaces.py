"""Marketplace API routes.

Exposes the marketplace abstraction layer. This router talks ONLY through the
`MarketplaceManager` (which in turn yields `MarketplaceProvider` interface
objects) — no marketplace-specific logic lives in this file or anywhere in the
API layer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import get_marketplace_manager
from app.core.logging import get_logger
from app.marketplaces.errors import (
    MarketplaceAuthenticationError,
    MarketplaceConfigurationError,
    MarketplaceError,
    MarketplaceNotFoundError,
    MarketplaceRateLimitError,
    MarketplaceRequestError,
)
from app.marketplaces.manager import MarketplaceManager

logger = get_logger(__name__)

router = APIRouter(prefix="/marketplaces", tags=["marketplaces"])


def _to_http(exc: MarketplaceError) -> HTTPException:
    """Translate a marketplace error into an HTTP exception."""
    if isinstance(exc, MarketplaceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, MarketplaceConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, MarketplaceAuthenticationError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, MarketplaceRateLimitError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, MarketplaceRequestError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


async def _manager(
    mgr: MarketplaceManager = Depends(get_marketplace_manager),
) -> MarketplaceManager:
    return mgr


@router.get("")
async def list_marketplaces(
    mgr: MarketplaceManager = Depends(_manager),
) -> list[dict[str, str]]:
    """List all discovered marketplaces with metadata."""
    return mgr.list_marketplaces()


@router.get("/enabled")
async def list_enabled_marketplaces(
    mgr: MarketplaceManager = Depends(_manager),
) -> list[str]:
    """List codes of all enabled marketplaces."""
    return mgr.get_enabled_marketplaces()


@router.get("/{code}/capabilities")
async def get_capabilities(
    code: str,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, bool]:
    """Report which of the 12 capabilities a marketplace supports."""
    try:
        return mgr.get_capabilities(code)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc


@router.post("/{code}/search")
async def search(
    code: str,
    query: str = Query(..., min_length=1, description="Search keyword"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    mgr: MarketplaceManager = Depends(_manager),
) -> list[dict[str, Any]]:
    """Search a marketplace catalog by keyword."""
    try:
        results = await mgr.search(code, query, page=page, page_size=page_size)
        return [r.model_dump() for r in results]
    except MarketplaceError as exc:
        raise _to_http(exc) from exc


@router.post("/search-all")
async def search_all(
    query: str = Query(..., min_length=1, description="Search keyword"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, list[dict[str, Any]]]:
    """Search across all enabled marketplaces (failures isolated)."""
    results = await mgr.search_all(query, page=page, page_size=page_size)
    return {code: [r.model_dump() for r in items] for code, items in results.items()}


@router.get("/{code}/products/{external_id}")
async def lookup(
    code: str,
    external_id: str,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, Any]:
    """Look up a product on a marketplace by its identifier."""
    try:
        product = await mgr.lookup(code, external_id)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product.model_dump()


@router.get("/{code}/products/{external_id}/pricing")
async def pricing(
    code: str,
    external_id: str,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, Any]:
    """Get pricing for a product on a marketplace."""
    try:
        result = await mgr.pricing(code, external_id)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Pricing not found")
    return result.model_dump()


@router.get("/{code}/products/{external_id}/fees")
async def fees(
    code: str,
    external_id: str,
    price: str | None = None,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, Any]:
    """Get fees for a product on a marketplace."""
    try:
        result = await mgr.fees(code, external_id, price=price)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fees not found")
    return result.model_dump()


@router.get("/{code}/products/{external_id}/inventory")
async def inventory(
    code: str,
    external_id: str,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, Any]:
    """Get inventory for a product on a marketplace."""
    try:
        result = await mgr.inventory(code, external_id)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Inventory not found")
    return result.model_dump()


@router.get("/{code}/products/{external_id}/competition")
async def competition(
    code: str,
    external_id: str,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, Any]:
    """Get competition for a product on a marketplace."""
    try:
        result = await mgr.competition(code, external_id)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    return result.model_dump()


@router.get("/{code}/products/{external_id}/sales-estimate")
async def sales_estimate(
    code: str,
    external_id: str,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, Any]:
    """Get a sales estimate for a product on a marketplace."""
    try:
        result = await mgr.sales_estimate(code, external_id)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Sales estimate not found")
    return result.model_dump()


@router.get("/{code}/products/{external_id}/buybox")
async def buybox(
    code: str,
    external_id: str,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, Any]:
    """Get Buy Box status for a product on a marketplace."""
    try:
        result = await mgr.buybox(code, external_id)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Buy Box not found")
    return result.model_dump()


@router.get("/{code}/products/{external_id}/shipping")
async def shipping(
    code: str,
    external_id: str,
    quantity: int = Query(1, ge=1),
    postal_code: str | None = None,
    mgr: MarketplaceManager = Depends(_manager),
) -> dict[str, Any]:
    """Get shipping options for a product on a marketplace."""
    try:
        result = await mgr.shipping(code, external_id, quantity=quantity, postal_code=postal_code)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Shipping not found")
    return result.model_dump()


@router.get("/{code}/orders")
async def orders(
    code: str,
    limit: int = Query(50, ge=1, le=200),
    mgr: MarketplaceManager = Depends(_manager),
) -> list[dict[str, Any]]:
    """Get recent orders from a marketplace."""
    try:
        results = await mgr.orders(code, limit=limit)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    return [r.model_dump() for r in results]


@router.get("/{code}/listings")
async def listings(
    code: str,
    status: str | None = None,
    mgr: MarketplaceManager = Depends(_manager),
) -> list[dict[str, Any]]:
    """Get the seller's listings on a marketplace."""
    try:
        results = await mgr.listings(code, status=status)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    return [r.model_dump() for r in results]


@router.get("/{code}/returns")
async def returns(
    code: str,
    limit: int = Query(50, ge=1, le=200),
    mgr: MarketplaceManager = Depends(_manager),
) -> list[dict[str, Any]]:
    """Get recent returns from a marketplace."""
    try:
        results = await mgr.returns(code, limit=limit)
    except MarketplaceError as exc:
        raise _to_http(exc) from exc
    return [r.model_dump() for r in results]
