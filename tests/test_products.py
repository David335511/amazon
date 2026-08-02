"""Tests for product API endpoints and service layer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.domain.schemas.product import ProductCreate
from app.domain.services.product_service import (
    ProductASINConflictError,
    ProductNotFoundError,
    ProductService,
)
from app.infrastructure.repositories.product_repository import ProductRepository


# ── API Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_product(client: AsyncClient, product_payload: dict[str, Any]) -> None:
    """Test creating a product via the API."""
    response = await client.post("/api/v1/products/", json=product_payload)
    assert response.status_code == 201
    data = response.json()
    assert data["asin"] == product_payload["asin"]
    assert data["title"] == product_payload["title"]
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
@pytest.mark.usefixtures("created_product")
async def test_create_product_duplicate_asin(
    client: AsyncClient,
    product_payload: dict[str, Any],
) -> None:
    """Test that creating a product with a duplicate ASIN returns 409."""
    response = await client.post("/api/v1/products/", json=product_payload)
    assert response.status_code == 409
    data = response.json()
    assert data["error"] == "asin_conflict"
    assert data["asin"] == product_payload["asin"]


@pytest.mark.asyncio
async def test_get_product(client: AsyncClient, created_product: dict[str, Any]) -> None:
    """Test retrieving a product by ID."""
    product_id = created_product["id"]
    response = await client.get(f"/api/v1/products/{product_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == product_id
    assert data["title"] == created_product["title"]


@pytest.mark.asyncio
async def test_get_product_not_found(client: AsyncClient) -> None:
    """Test that getting a non-existent product returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/api/v1/products/{fake_id}")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "product_not_found"


@pytest.mark.asyncio
@pytest.mark.usefixtures("created_product")
async def test_list_products(
    client: AsyncClient,
) -> None:
    """Test listing products with pagination."""
    response = await client.get("/api/v1/products/")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    assert data["page"] == 1
    assert data["page_size"] == 20


@pytest.mark.asyncio
@pytest.mark.usefixtures("created_product")
async def test_list_products_with_search(
    client: AsyncClient,
) -> None:
    """Test searching products by title."""
    response = await client.get(
        "/api/v1/products/",
        params={"search": "Test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_update_product(
    client: AsyncClient,
    created_product: dict[str, Any],
) -> None:
    """Test updating a product."""
    product_id = created_product["id"]
    update_payload = {"title": "Updated Product Title"}
    response = await client.patch(f"/api/v1/products/{product_id}", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Product Title"
    # Unchanged fields should remain
    assert data["asin"] == created_product["asin"]


@pytest.mark.asyncio
async def test_delete_product(
    client: AsyncClient,
    created_product: dict[str, Any],
) -> None:
    """Test deleting a product."""
    product_id = created_product["id"]
    response = await client.delete(f"/api/v1/products/{product_id}")
    assert response.status_code == 204

    # Verify it's gone
    get_response = await client.get(f"/api/v1/products/{product_id}")
    assert get_response.status_code == 404


# ── Service Layer Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_product_service_create(
    db_session: Any,
    product_payload: dict[str, Any],
) -> None:
    """Test the product service create method directly."""
    repo = ProductRepository(db_session)
    service = ProductService(repo)
    data = ProductCreate(**product_payload)
    product = await service.create_product(data)
    assert product.title == product_payload["title"]
    assert product.asin == product_payload["asin"]


@pytest.mark.asyncio
async def test_product_service_asin_conflict(
    db_session: Any,
    product_payload: dict[str, Any],
) -> None:
    """Test that creating a product with a duplicate ASIN raises an error."""
    repo = ProductRepository(db_session)
    service = ProductService(repo)
    data = ProductCreate(**product_payload)
    await service.create_product(data)
    with pytest.raises(ProductASINConflictError):
        await service.create_product(data)


@pytest.mark.asyncio
async def test_product_service_not_found(db_session: Any) -> None:
    """Test that getting a non-existent product raises an error."""
    repo = ProductRepository(db_session)
    service = ProductService(repo)
    fake_id = UUID("00000000-0000-0000-0000-000000000000")
    with pytest.raises(ProductNotFoundError):
        await service.get_product(fake_id)
