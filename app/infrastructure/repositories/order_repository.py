"""Order repository with domain-specific queries."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.order import Order, OrderItem
from app.infrastructure.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    """Repository for Order entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Order)

    async def get_with_items(self, order_id: UUID) -> Order | None:
        """Get an order with its line items eagerly loaded."""
        query = select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def find_by_customer(
        self,
        customer_id: UUID,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Order], int]:
        """Find all orders for a customer with pagination."""
        return await self.get_many(
            skip=skip,
            limit=limit,
            filters={"customer_id": customer_id},
            order_by="created_at",
            descending=True,
        )

    async def find_by_status(
        self,
        status: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Order], int]:
        """Find orders by status with pagination."""
        return await self.get_many(
            skip=skip,
            limit=limit,
            filters={"status": status},
            order_by="created_at",
            descending=True,
        )

    async def add_order_item(
        self,
        order_id: UUID,
        product_id: UUID,
        quantity: int,
        unit_price: Decimal,
        currency: str = "USD",
    ) -> OrderItem:
        """Add a line item to an order."""
        item = OrderItem(
            order_id=order_id,
            product_id=product_id,
            quantity=quantity,
            unit_price=unit_price,
            currency=currency,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def update_status(
        self,
        order_id: UUID,
        status: str,
    ) -> Order | None:
        """Update the status of an order."""
        return await self.update(order_id, status=status)
