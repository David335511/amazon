"""Order service — business logic for order operations.

Design decisions:
- Order creation validates stock availability before committing.
- Stock is reduced atomically when an order is confirmed.
- Status transitions follow a defined state machine.
- The service orchestrates across multiple repositories if needed.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from app.domain.models.order import Order
from app.domain.schemas.order import OrderCreate, OrderStatusUpdate
from app.infrastructure.repositories.order_repository import OrderRepository
from app.infrastructure.repositories.product_repository import ProductRepository

from .product_service import InsufficientStockError, ProductNotFoundError


class OrderNotFoundError(Exception):
    """Raised when an order is not found."""

    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        super().__init__(f"Order not found: {order_id}")


class InvalidOrderStatusTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from '{current}' to '{target}'")


# Valid status transitions
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped": {"delivered", "cancelled"},
    "delivered": {"refunded"},
    "cancelled": set(),
    "refunded": set(),
}


class OrderService:
    """Business logic for order management."""

    def __init__(
        self,
        order_repository: OrderRepository,
        product_repository: ProductRepository | None = None,
    ) -> None:
        self._order_repository = order_repository
        self._product_repository = product_repository or ProductRepository(
            order_repository._session,
        )

    async def create_order(self, data: OrderCreate) -> Order:
        """Create a new order with line items.

        Validates stock availability for all items before creating.
        """
        # Validate stock for all items first
        for item in data.items:
            product = await self._product_repository.get(item.product_id)
            if product is None:
                raise ProductNotFoundError(item.product_id)
            if not product.has_available_stock(item.quantity):
                raise InsufficientStockError(
                    product_id=item.product_id,
                    requested=item.quantity,
                    available=product.stock_quantity,
                )

        # Create the order
        order = await self._order_repository.create(
            customer_id=data.customer_id,
            status="pending",
            total_amount=Decimal("0.00"),
            shipping_address=data.shipping_address,
            notes=data.notes,
        )

        # Add line items and calculate total
        total = Decimal("0.00")
        for item in data.items:
            product = await self._product_repository.get(item.product_id)
            if product is None:
                raise ProductNotFoundError(item.product_id)

            await self._order_repository.add_order_item(
                order_id=order.id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=product.price,
                currency=product.currency,
            )
            total += product.price * item.quantity

        # Update order total
        await self._order_repository.update(order.id, total_amount=total)

        # Reload with items
        result = await self._order_repository.get_with_items(order.id)
        if result is None:
            raise OrderNotFoundError(order.id)
        return result

    async def get_order(self, order_id: UUID) -> Order:
        """Get an order by ID with line items.

        Raises OrderNotFoundError if not found.
        """
        order = await self._order_repository.get_with_items(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)
        return order

    async def list_orders(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        customer_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[Sequence[Order], int]:
        """List orders with optional filtering and pagination.

        Returns:
            Tuple of (orders, total_count).
        """
        skip = (page - 1) * page_size

        if customer_id:
            return await self._order_repository.find_by_customer(
                customer_id,
                skip=skip,
                limit=page_size,
            )
        if status:
            return await self._order_repository.find_by_status(
                status,
                skip=skip,
                limit=page_size,
            )

        return await self._order_repository.get_many(
            skip=skip,
            limit=page_size,
            order_by="created_at",
            descending=True,
        )

    async def update_order_status(
        self,
        order_id: UUID,
        data: OrderStatusUpdate,
    ) -> Order:
        """Update the status of an order with transition validation.

        Raises OrderNotFoundError or InvalidOrderStatusTransitionError.
        """
        order = await self._order_repository.get(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)

        # Validate status transition
        allowed = ALLOWED_TRANSITIONS.get(order.status, set())
        if data.status not in allowed:
            raise InvalidOrderStatusTransitionError(order.status, data.status)

        # If confirming, reduce stock
        if data.status == "confirmed" and order.status == "pending":
            order_with_items = await self._order_repository.get_with_items(order_id)
            if order_with_items is None:
                raise OrderNotFoundError(order_id)
            for item in order_with_items.items:
                product = await self._product_repository.get(item.product_id)
                if product is not None:
                    product.reduce_stock(item.quantity)

        # Update status
        update_kwargs: dict[str, str] = {"status": data.status}
        if data.notes:
            update_kwargs["notes"] = data.notes

        updated = await self._order_repository.update(order_id, **update_kwargs)
        if updated is None:
            raise OrderNotFoundError(order_id)
        return updated

    async def cancel_order(self, order_id: UUID) -> Order:
        """Cancel an order and restore stock if it was confirmed."""
        return await self.update_order_status(
            order_id,
            OrderStatusUpdate(status="cancelled"),
        )
