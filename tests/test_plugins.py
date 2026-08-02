"""Tests for the supplier plugin architecture.

Tests the plugin interface, registry, manager, and sample plugins.
Uses mocked HTTP responses to avoid hitting real supplier APIs.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.plugins.base import BaseSupplierPlugin
from app.plugins.config import SupplierConfig, SupplierPluginConfig
from app.plugins.errors import PluginNotFoundError
from app.plugins.manager import PluginManager
from app.plugins.models import (
    SupplierAvailability,
    SupplierCoupon,
    SupplierInventory,
    SupplierPricing,
    SupplierProductLookup,
    SupplierProductSearchResult,
    SupplierShipping,
)
from app.plugins.registry import PluginRegistry
from app.plugins.suppliers.bestbuy import BestBuyPlugin
from app.plugins.suppliers.costco import CostcoPlugin
from app.plugins.suppliers.homedepot import HomeDepotPlugin
from app.plugins.suppliers.target import TargetPlugin
from app.plugins.suppliers.walmart import WalmartPlugin


# ── Plugin Interface Tests ───────────────────────────────────


class TestBasePluginInterface:
    """Test that the base plugin interface enforces the contract."""

    def test_plugin_has_required_attributes(self) -> None:
        """Test that all plugins have required class attributes."""
        plugins = [WalmartPlugin, TargetPlugin, HomeDepotPlugin, CostcoPlugin, BestBuyPlugin]

        for plugin_class in plugins:
            assert plugin_class.supplier_name, f"{plugin_class.__name__} missing supplier_name"
            assert plugin_class.supplier_code, f"{plugin_class.__name__} missing supplier_code"
            assert plugin_class.version, f"{plugin_class.__name__} missing version"

    def test_plugin_implements_all_methods(self) -> None:
        """Test that all plugins implement all 8 required methods."""
        plugins = [WalmartPlugin, TargetPlugin, HomeDepotPlugin, CostcoPlugin, BestBuyPlugin]
        required = ["search", "lookup", "pricing", "inventory", "shipping", "coupon", "availability"]

        for plugin_class in plugins:
            instance = plugin_class()
            for method in required:
                assert hasattr(instance, method), (
                    f"{plugin_class.__name__} missing method '{method}'"
                )
                assert callable(getattr(instance, method)), (
                    f"{plugin_class.__name__}.{method} is not callable"
                )

    def test_plugin_codes_are_unique(self) -> None:
        """Test that all plugin codes are unique."""
        plugins = [WalmartPlugin, TargetPlugin, HomeDepotPlugin, CostcoPlugin, BestBuyPlugin]
        codes = [p.supplier_code for p in plugins]
        assert len(codes) == len(set(codes)), "Duplicate supplier codes found"


# ── Registry Tests ─────────────────────────────────────────


class TestPluginRegistry:
    """Test the plugin registry."""

    def test_discover_finds_all_plugins(self) -> None:
        """Test that discovery finds all 5 sample plugins."""
        registry = PluginRegistry()
        plugins = registry.discover()
        assert len(plugins) >= 5
        assert "walmart" in plugins
        assert "target" in plugins
        assert "homedepot" in plugins
        assert "costco" in plugins
        assert "bestbuy" in plugins

    def test_get_plugin_class(self) -> None:
        """Test getting a plugin class by code."""
        registry = PluginRegistry()
        registry.discover()
        cls = registry.get_plugin_class("walmart")
        assert cls == WalmartPlugin

    def test_get_plugin_class_not_found(self) -> None:
        """Test that getting a non-existent plugin raises error."""
        registry = PluginRegistry()
        registry.discover()
        with pytest.raises(PluginNotFoundError):
            registry.get_plugin_class("nonexistent")

    def test_create_plugin_instance(self) -> None:
        """Test creating a plugin instance."""
        registry = PluginRegistry()
        registry.discover()
        instance = registry.create("walmart")
        assert isinstance(instance, WalmartPlugin)
        assert instance.supplier_code == "walmart"

    def test_list_plugins(self) -> None:
        """Test listing all plugins."""
        registry = PluginRegistry()
        registry.discover()
        plugins = registry.list_plugins()
        codes = [p["code"] for p in plugins]
        assert "walmart" in codes
        assert "target" in codes

    def test_get_enabled_plugins(self) -> None:
        """Test getting enabled plugins with config."""
        registry = PluginRegistry()
        registry.discover()

        config = SupplierPluginConfig(
            suppliers={
                "walmart": SupplierConfig(code="walmart", name="Walmart", enabled=True),
                "target": SupplierConfig(code="target", name="Target", enabled=False),
            },
        )

        enabled = registry.get_enabled_plugins(config)
        assert "walmart" in enabled
        assert "target" not in enabled


# ── Plugin Manager Tests ────────────────────────────────────


class TestPluginManager:
    """Test the plugin manager."""

    @pytest.mark.asyncio
    async def test_initialize_and_shutdown(self) -> None:
        """Test initializing and shutting down the plugin manager."""
        registry = PluginRegistry()
        registry.discover()

        config = SupplierPluginConfig(
            suppliers={
                "walmart": SupplierConfig(code="walmart", name="Walmart", enabled=True),
            },
        )

        manager = PluginManager(registry=registry, config=config)
        await manager.initialize()
        assert manager._initialized

        await manager.shutdown()
        assert not manager._initialized

    def test_list_suppliers(self) -> None:
        """Test listing suppliers."""
        registry = PluginRegistry()
        registry.discover()
        manager = PluginManager(registry=registry)
        suppliers = manager.list_suppliers()
        assert len(suppliers) >= 5

    def test_get_enabled_suppliers(self) -> None:
        """Test getting enabled suppliers."""
        registry = PluginRegistry()
        registry.discover()
        config = SupplierPluginConfig(
            suppliers={
                "walmart": SupplierConfig(code="walmart", name="Walmart", enabled=True),
                "target": SupplierConfig(code="target", name="Target", enabled=True),
                "homedepot": SupplierConfig(code="homedepot", name="Home Depot", enabled=True),
                "costco": SupplierConfig(code="costco", name="Costco", enabled=True),
                "bestbuy": SupplierConfig(code="bestbuy", name="Best Buy", enabled=True),
            },
        )
        manager = PluginManager(registry=registry, config=config)
        enabled = manager.get_enabled_suppliers()
        assert len(enabled) >= 5


# ── Sample Plugin Tests ─────────────────────────────────────


class TestWalmartPlugin:
    """Test the Walmart plugin with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self) -> None:
        """Test that search returns typed results."""
        from unittest.mock import MagicMock

        plugin = WalmartPlugin()
        mock_response = {
            "items": [
                {
                    "sku": "WM12345",
                    "title": "Test Product",
                    "upc": "123456789012",
                    "brand": "TestBrand",
                    "price": 29.99,
                    "inStock": True,
                },
            ],
        }

        mock_client = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = mock_response
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        plugin._http_client = mock_client

        results = await plugin.search("test")
        assert len(results) == 1
        assert isinstance(results[0], SupplierProductSearchResult)
        assert results[0].supplier_sku == "WM12345"
        assert results[0].title == "Test Product"
        assert results[0].price == Decimal("29.99")

    @pytest.mark.asyncio
    async def test_lookup_returns_details(self) -> None:
        """Test that lookup returns typed product details."""
        from unittest.mock import MagicMock

        plugin = WalmartPlugin()
        mock_response = {
            "sku": "WM12345",
            "title": "Test Product",
            "description": "A test product",
            "upc": "123456789012",
            "brand": "TestBrand",
            "price": 29.99,
        }

        mock_client = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = mock_response
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        plugin._http_client = mock_client

        result = await plugin.lookup("WM12345")
        assert result is not None
        assert isinstance(result, SupplierProductLookup)
        assert result.title == "Test Product"
        assert result.price == Decimal("29.99")

    @pytest.mark.asyncio
    async def test_lookup_not_found(self) -> None:
        """Test that lookup returns None for missing products."""
        plugin = WalmartPlugin()

        with patch.object(plugin, "get_http_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value.status_code = 404
            mock_get_client.return_value = mock_client

            result = await plugin.lookup("WM99999")
            assert result is None

    @pytest.mark.asyncio
    async def test_pricing(self) -> None:
        """Test pricing returns typed data."""
        plugin = WalmartPlugin()

        with patch.object(plugin, "lookup") as mock_lookup:
            mock_lookup.return_value = SupplierProductLookup(
                supplier_sku="WM12345",
                title="Test",
                price=Decimal("29.99"),
            )
            result = await plugin.pricing("WM12345")
            assert result is not None
            assert isinstance(result, SupplierPricing)
            assert result.unit_price == Decimal("29.99")

    @pytest.mark.asyncio
    async def test_inventory(self) -> None:
        """Test inventory returns typed data."""
        from unittest.mock import MagicMock

        plugin = WalmartPlugin()

        mock_client = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = {
            "availableQuantity": 100,
            "backorderable": True,
        }
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        plugin._http_client = mock_client

        result = await plugin.inventory("WM12345")
        assert result is not None
        assert isinstance(result, SupplierInventory)
        assert result.quantity_available == 100
        assert result.is_backorderable is True

    @pytest.mark.asyncio
    async def test_shipping(self) -> None:
        """Test shipping returns typed data."""
        plugin = WalmartPlugin()
        result = await plugin.shipping("WM12345")
        assert result is not None
        assert isinstance(result, SupplierShipping)
        assert len(result.methods) > 0

    @pytest.mark.asyncio
    async def test_coupon(self) -> None:
        """Test coupon returns typed data."""
        plugin = WalmartPlugin()
        results = await plugin.coupon()
        assert len(results) > 0
        assert isinstance(results[0], SupplierCoupon)
        assert results[0].code == "WELCOME10"

    @pytest.mark.asyncio
    async def test_availability(self) -> None:
        """Test availability returns typed data."""
        plugin = WalmartPlugin()

        with patch.object(plugin, "inventory") as mock_inv:
            mock_inv.return_value = SupplierInventory(
                supplier_sku="WM12345",
                quantity_available=50,
                is_backorderable=False,
            )
            result = await plugin.availability("WM12345")
            assert result is not None
            assert isinstance(result, SupplierAvailability)
            assert result.is_available is True
            assert result.stock_status == "in_stock"


class TestTargetPlugin:
    """Test the Target plugin."""

    @pytest.mark.asyncio
    async def test_search(self) -> None:
        """Test Target search returns typed results."""
        from unittest.mock import MagicMock

        plugin = TargetPlugin()

        mock_client = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = {
            "products": [
                {
                    "partnerProductId": "TGT12345",
                    "title": "Target Product",
                    "price": 19.99,
                },
            ],
        }
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        plugin._http_client = mock_client

        results = await plugin.search("test")
        assert len(results) == 1
        assert results[0].supplier_sku == "TGT12345"
        assert results[0].price == Decimal("19.99")


class TestHomeDepotPlugin:
    """Test the Home Depot plugin."""

    @pytest.mark.asyncio
    async def test_pricing_with_tiers(self) -> None:
        """Test Home Depot pricing includes volume tiers."""
        plugin = HomeDepotPlugin()

        with patch.object(plugin, "lookup") as mock_lookup:
            mock_lookup.return_value = SupplierProductLookup(
                supplier_sku="HD12345",
                title="Test",
                price=Decimal("100.00"),
            )
            result = await plugin.pricing("HD12345")
            assert result is not None
            assert len(result.quantity_tiers) == 3
            assert result.quantity_tiers[0]["min_qty"] == 10
            assert result.quantity_tiers[0]["price"] == Decimal("95.00")


class TestCostcoPlugin:
    """Test the Costco plugin."""

    @pytest.mark.asyncio
    async def test_search(self) -> None:
        """Test Costco search returns typed results."""
        from unittest.mock import MagicMock

        plugin = CostcoPlugin()

        mock_client = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = {
            "items": [
                {
                    "itemNumber": "COST12345",
                    "name": "Costco Product",
                    "price": 49.99,
                },
            ],
        }
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        plugin._http_client = mock_client

        results = await plugin.search("test")
        assert len(results) == 1
        assert results[0].supplier_sku == "COST12345"


class TestBestBuyPlugin:
    """Test the Best Buy plugin."""

    @pytest.mark.asyncio
    async def test_search(self) -> None:
        """Test Best Buy search returns typed results."""
        from unittest.mock import MagicMock

        plugin = BestBuyPlugin()

        mock_client = AsyncMock()
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = {
            "products": [
                {
                    "sku": "BB12345",
                    "name": "Best Buy Product",
                    "salePrice": 899.99,
                },
            ],
        }
        mock_client.get = AsyncMock(return_value=mock_response_obj)
        plugin._http_client = mock_client

        results = await plugin.search("test")
        assert len(results) == 1
        assert results[0].supplier_sku == "BB12345"
        assert results[0].price == Decimal("899.99")

    @pytest.mark.asyncio
    async def test_shipping_includes_store_pickup(self) -> None:
        """Test Best Buy shipping includes store pickup option."""
        plugin = BestBuyPlugin()
        result = await plugin.shipping("BB12345")
        assert result is not None
        methods = [m["name"] for m in result.methods]
        assert "Store Pickup" in methods
