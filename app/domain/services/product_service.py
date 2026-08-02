"""Product service — business logic for product operations.

Design decisions:
- Services contain all business rules and orchestration.
- They depend on repositories (not directly on the database session).
- Input validation is done by Pydantic schemas before reaching services.
- Services raise domain-specific exceptions that API handlers translate to HTTP responses.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domain.models.product import Product
from app.domain.schemas.product import ProductCreate, ProductUpdate
from app.infrastructure.repositories.product_repository import ProductRepository


class ProductNotFoundError(Exception):
    """Raised when a product is not found."""

    def __init__(self, product_id: UUID) -> None:
        self.product_id = product_id
        super().__init__(f"Product not found: {product_id}")


class ProductASINConflictError(Exception):
    """Raised when a product ASIN already exists."""

    def __init__(self, asin: str) -> None:
        self.asin = asin
        super().__init__(f"Product with ASIN '{asin}' already exists")


class InsufficientStockError(Exception):
    """Raised when there is not enough stock for a product."""

    def __init__(self, product_id: UUID, requested: int, available: int) -> None:
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for product {product_id}: "
            f"requested {requested}, available {available}",
        )


class ProductService:
    """Business logic for product management."""

    def __init__(self, repository: ProductRepository) -> None:
        self._repository = repository

    async def create_product(self, data: ProductCreate) -> Product:
        """Create a new product.

        Raises ProductASINConflictError if the ASIN already exists.
        """
        existing = await self._repository.find_by_asin(data.asin)
        if existing is not None:
            raise ProductASINConflictError(data.asin)

        return await self._repository.create(
            asin=data.asin,
            title=data.title,
            description=data.description,
            price=data.price,
            currency=data.currency,
            upc=data.upc,
            ean=data.ean,
            gtin=data.gtin,
            brand_id=data.brand_id,
            category_id=data.category_id,
            main_image_url=data.main_image_url,
            weight=data.weight,
            weight_unit=data.weight_unit,
            dimensions=data.dimensions,
            is_active=True,
        )

    async def get_product(self, product_id: UUID) -> Product:
        """Get a product by ID.

        Raises ProductNotFoundError if not found.
        """
        product = await self._repository.get(product_id)
        if product is None:
            raise ProductNotFoundError(product_id)
        return product

    async def get_product_by_asin(self, asin: str) -> Product:
        """Get a product by ASIN.

        Raises ProductNotFoundError if not found.
        """
        product = await self._repository.find_by_asin(asin)
        if product is None:
            msg = f"Product with ASIN '{asin}' not found"
            raise ProductNotFoundError(UUID(int=0))  # Placeholder
        return product

    async def list_products(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        category_id: str | None = None,
        search: str | None = None,
        brand_id: str | None = None,
    ) -> tuple[Sequence[Product], int]:
        """List products with optional filtering and pagination.

        Returns:
            Tuple of (products, total_count).
        """
        skip = (page - 1) * page_size

        if search:
            return await self._repository.search(search, skip=skip, limit=page_size)
        if category_id:
            return await self._repository.find_by_category_id(
                category_id,
                skip=skip,
                limit=page_size,
            )
        if brand_id:
            return await self._repository.find_by_brand(
                brand_id,
                skip=skip,
                limit=page_size,
            )

        return await self._repository.get_active_products(skip=skip, limit=page_size)

    async def update_product(self, product_id: UUID, data: ProductUpdate) -> Product:
        """Update a product.

        Raises ProductNotFoundError if not found.
        Only updates fields that are explicitly set (not None).
        """
        product = await self._repository.get(product_id)
        if product is None:
            raise ProductNotFoundError(product_id)

        update_kwargs = data.model_dump(exclude_unset=True)
        updated = await self._repository.update(product_id, **update_kwargs)
        if updated is None:
            raise ProductNotFoundError(product_id)
        return updated

    async def delete_product(self, product_id: UUID) -> None:
        """Delete a product.

        Raises ProductNotFoundError if not found.
        """
        deleted = await self._repository.delete(product_id)
        if not deleted:
            raise ProductNotFoundError(product_id)

    async def check_stock(
        self,
        product_id: UUID,
        quantity: int,
    ) -> Product:
        """Check if a product has sufficient stock.

        Raises ProductNotFoundError or InsufficientStockError.
        """
        product = await self.get_product(product_id)
        if not product.has_available_stock(quantity):
            raise InsufficientStockError(
                product_id=product_id,
                requested=quantity,
                available=product.stock_quantity,
            )
        return product
