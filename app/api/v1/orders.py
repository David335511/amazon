"""Order API routes.

Design decisions:
- Order creation is a single POST that validates stock and creates line items.
- Status updates follow a state machine enforced by the service layer.
- Cancellation is a dedicated endpoint for clarity.
"""

from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import get_order_service
from app.domain.schemas.order import (
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    OrderStatusUpdate,
)
from app.domain.services.order_service import (
    OrderService,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post(
    "/",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order",
)
async def create_order(
    data: OrderCreate,
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """Create a new order with line items.

    Validates stock availability for all items before creating.
    """
    order = await service.create_order(data)
    return OrderResponse.model_validate(order)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get an order by ID",
)
async def get_order(
    order_id: UUID,
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """Retrieve an order by its UUID with all line items."""
    order = await service.get_order(order_id)
    return OrderResponse.model_validate(order)


@router.get(
    "/",
    response_model=OrderListResponse,
    summary="List orders",
)
async def list_orders(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    customer_id: UUID | None = Query(default=None, description="Filter by customer"),
    status: str | None = Query(default=None, description="Filter by status"),
    service: OrderService = Depends(get_order_service),
) -> OrderListResponse:
    """List orders with optional filtering and pagination."""
    orders, total = await service.list_orders(
        page=page,
        page_size=page_size,
        customer_id=customer_id,
        status=status,
    )
    return OrderListResponse(
        items=[OrderResponse.model_validate(o) for o in orders],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
    )


@router.patch(
    "/{order_id}/status",
    response_model=OrderResponse,
    summary="Update order status",
)
async def update_order_status(
    order_id: UUID,
    data: OrderStatusUpdate,
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """Update the status of an order.

    Validates status transitions (e.g., pending → confirmed, not pending → delivered).
    """
    order = await service.update_order_status(order_id, data)
    return OrderResponse.model_validate(order)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Cancel an order",
)
async def cancel_order(
    order_id: UUID,
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """Cancel an order and restore stock if it was confirmed."""
    order = await service.cancel_order(order_id)
    return OrderResponse.model_validate(order)
