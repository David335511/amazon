"""Product API routes.

Design decisions:
- Thin route handlers that delegate to the service layer.
- HTTP status codes follow REST conventions (201 for create, 204 for delete).
- Exception handlers translate domain exceptions to HTTP responses.
- Pagination uses query parameters with sensible defaults.
"""

from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_product_service
from app.domain.schemas.product import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.domain.services.product_service import (
    ProductService,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new product",
)
async def create_product(
    data: ProductCreate,
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Create a new product in the catalog."""
    product = await service.create_product(data)
    return ProductResponse.model_validate(product)


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get a product by ID",
)
async def get_product(
    product_id: UUID,
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Retrieve a product by its UUID."""
    product = await service.get_product(product_id)
    return ProductResponse.model_validate(product)


@router.get(
    "/",
    response_model=ProductListResponse,
    summary="List products",
)
async def list_products(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    category_id: str | None = Query(default=None, description="Filter by category ID"),
    brand_id: str | None = Query(default=None, description="Filter by brand ID"),
    search: str | None = Query(default=None, description="Search by title or description"),
    service: ProductService = Depends(get_product_service),
) -> ProductListResponse:
    """List products with optional filtering and pagination."""
    products, total = await service.list_products(
        page=page,
        page_size=page_size,
        category_id=category_id,
        brand_id=brand_id,
        search=search,
    )
    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in products],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
    )


@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update a product",
)
async def update_product(
    product_id: UUID,
    data: ProductUpdate,
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Update an existing product (partial update)."""
    product = await service.update_product(product_id, data)
    return ProductResponse.model_validate(product)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product",
)
async def delete_product(
    product_id: UUID,
    service: ProductService = Depends(get_product_service),
) -> None:
    """Delete a product from the catalog."""
    await service.delete_product(product_id)
