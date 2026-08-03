"""Tests for the marketplace abstraction layer.

Verifies:
- The `MarketplaceProvider` interface contract (all 12 methods implemented by
  every concrete provider).
- Auto-discovery via the registry.
- Capability reporting per provider.
- Error isolation across marketplaces in the manager.
- That the rest of the platform (api/domain) does NOT depend on concrete
  marketplace providers (no marketplace-specific logic outside providers).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.marketplaces.base import CAPABILITIES, MarketplaceProvider
from app.marketplaces.errors import MarketplaceNotFoundError
from app.marketplaces.manager import MarketplaceManager
from app.marketplaces.models import MarketplaceFees, MarketplacePricing
from app.marketplaces.registry import MarketplaceRegistry

# Expected unsupported capabilities per marketplace code.
EXPECTED_UNSUPPORTED: dict[str, frozenset[str]] = {
    "amazon": frozenset({"sales_estimate"}),
    "ebay": frozenset({"fees", "sales_estimate", "returns"}),
    "walmart": frozenset({"fees", "competition", "sales_estimate", "buybox", "shipping"}),
    "tiktok": frozenset(
        {"search", "lookup", "pricing", "fees", "competition", "sales_estimate", "buybox", "shipping"}
    ),
    "facebook": frozenset(
        {"search", "lookup", "pricing", "fees", "inventory", "competition",
         "sales_estimate", "buybox", "shipping", "returns"}
    ),
    "etsy": frozenset(
        {"inventory", "competition", "sales_estimate", "buybox", "shipping", "returns"}
    ),
}


def _concrete_providers() -> list[type[MarketplaceProvider]]:
    """Return all concrete provider classes discovered by the registry."""
    registry = MarketplaceRegistry()
    discovered = registry.discover()
    return list(discovered.values())


@pytest.fixture
def registry() -> MarketplaceRegistry:
    return MarketplaceRegistry()


# ── Contract: every provider implements all 12 methods ─────


class TestProviderContract:
    def test_all_12_capabilities_defined(self) -> None:
        assert len(CAPABILITIES) == 12
        assert set(CAPABILITIES) == {
            "search", "lookup", "pricing", "fees", "inventory", "orders",
            "listings", "competition", "sales_estimate", "buybox", "shipping", "returns",
        }

    def test_every_provider_implements_all_12(self) -> None:
        """No provider may leave any of the 12 methods abstract."""
        for cls in _concrete_providers():
            for cap in CAPABILITIES:
                method = getattr(cls, cap)
                assert not getattr(method, "__isabstractmethod__", False), (
                    f"{cls.marketplace_code} has not implemented '{cap}'"
                )

    def test_every_provider_is_concrete_instantiable(self) -> None:
        for cls in _concrete_providers():
            provider = cls(config={})
            assert isinstance(provider, MarketplaceProvider)

    def test_providers_have_identity(self) -> None:
        for cls in _concrete_providers():
            assert cls.marketplace_code
            assert cls.marketplace_name
            assert cls.version


# ── Discovery ───────────────────────────────────────────────


class TestDiscovery:
    def test_discovers_all_six_marketplaces(self, registry: MarketplaceRegistry) -> None:
        registry.discover()
        providers = registry.list_providers()
        codes = {p["code"] for p in providers}
        assert {"amazon", "ebay", "walmart", "tiktok", "facebook", "etsy"} <= codes

    def test_get_provider_class(self, registry: MarketplaceRegistry) -> None:
        cls = registry.get_provider_class("amazon")
        assert cls.marketplace_code == "amazon"

    def test_get_unknown_raises(self, registry: MarketplaceRegistry) -> None:
        with pytest.raises(MarketplaceNotFoundError):
            registry.get_provider_class("not-a-marketplace")

    def test_instances_are_cached(self, registry: MarketplaceRegistry) -> None:
        a = registry.get("amazon", config={})
        b = registry.get("amazon", config={})
        assert a is b


# ── Capability reporting ────────────────────────────────────


class TestCapabilities:
    def test_capabilities_match_declarations(self) -> None:
        for cls in _concrete_providers():
            provider = cls(config={})
            caps = provider.capabilities()
            assert len(caps) == 12
            for cap in CAPABILITIES:
                expected = cap not in EXPECTED_UNSUPPORTED[provider.marketplace_code]
                assert caps[cap] is expected, (
                    f"{provider.marketplace_code}.{cap} should be {expected}"
                )

    def test_manager_get_capabilities(self) -> None:
        manager = MarketplaceManager()
        caps = manager.get_capabilities("amazon")
        assert caps["sales_estimate"] is False
        assert caps["search"] is True


# ── Graceful degradation ────────────────────────────────────


class TestGracefulDegradation:
    def test_etsy_fees_are_computed(self) -> None:
        from app.marketplaces.providers.etsy import EtsyMarketplace

        provider = EtsyMarketplace(config={"api_key": "test", "extra": {}})
        fees = asyncio.run(provider.fees("123", price=100))
        assert isinstance(fees, MarketplaceFees)
        assert fees.supported is True
        # 6.5% + 3% + 0.25 on 100 = 9.75
        assert fees.fee_total == pytest.approx(9.75)

    def test_unsupported_returns_supported_false(self) -> None:
        from app.marketplaces.providers.tiktok import TikTokShopMarketplace

        provider = TikTokShopMarketplace(config={})
        result = asyncio.run(provider.pricing("x"))
        assert isinstance(result, MarketplacePricing)
        assert result.supported is False

    def test_unsupported_list_returns_empty(self) -> None:
        from app.marketplaces.providers.tiktok import TikTokShopMarketplace

        provider = TikTokShopMarketplace(config={})
        results = asyncio.run(provider.search("x"))
        assert results == []


# ── Manager error isolation ─────────────────────────────────


class _FakeMarketplace(MarketplaceProvider):
    """A fake provider to exercise manager behavior without network."""

    marketplace_name = "Fake"
    marketplace_code = "fake"
    version = "1.0.0"

    async def search(self, query, *, page=1, page_size=20):  # noqa: ARG002
        return []

    async def lookup(self, external_id):  # noqa: ARG002
        return None

    async def pricing(self, external_id):  # noqa: ARG002
        return None

    async def fees(self, external_id, price=None):  # noqa: ARG002
        return None

    async def inventory(self, external_id):  # noqa: ARG002
        return None

    async def orders(self, *, limit=50):  # noqa: ARG002
        return []

    async def listings(self, *, status=None):  # noqa: ARG002
        return []

    async def competition(self, external_id):  # noqa: ARG002
        return None

    async def sales_estimate(self, external_id):  # noqa: ARG002
        return None

    async def buybox(self, external_id):  # noqa: ARG002
        return None

    async def shipping(self, external_id, *, quantity=1, postal_code=None):  # noqa: ARG002
        return None

    async def returns(self, *, limit=50):  # noqa: ARG002
        return []


class TestManagerIsolation:
    def test_search_all_isolates_failures(self) -> None:
        """A failing marketplace must not break other marketplaces."""

        class _Boom(_FakeMarketplace):
            marketplace_code = "boom"

            async def search(self, query, *, page=1, page_size=20):  # noqa: ARG002
                raise RuntimeError("provider exploded")

        from app.marketplaces import registry as reg

        fake_registry = reg.MarketplaceRegistry()
        fake_registry._providers = {
            "fake": _FakeMarketplace,
            "boom": _Boom,
        }
        fake_registry._discovered = True

        manager = MarketplaceManager(registry=fake_registry)
        results = asyncio.run(manager.search_all("headphones"))
        # 'boom' raised but was isolated; 'fake' returned empty (excluded).
        assert results == {}

    def test_unknown_marketplace_raises(self) -> None:
        manager = MarketplaceManager()
        with pytest.raises(MarketplaceNotFoundError):
            manager.get_capabilities("does-not-exist")


# ── No marketplace logic leaks outside providers ────────────


class TestBoundary:
    def test_api_layer_does_not_import_concrete_providers(self) -> None:
        """The API/service layer must never depend on concrete providers."""
        repo_root = Path(__file__).resolve().parent.parent
        offenders: list[str] = []
        for path in sorted((repo_root / "app" / "api").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "app.marketplaces.providers" in text:
                offenders.append(str(path))
        for path in sorted((repo_root / "app" / "domain").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "app.marketplaces.providers" in text:
                offenders.append(str(path))
        assert offenders == [], f"Concrete provider imported outside boundary: {offenders}"

    def test_amazon_not_hardcoded_outside_provider(self) -> None:
        """The string 'amazon' as a marketplace must not appear in API routes."""
        # The API router references marketplaces generically by code; ensure no
        # route hardcodes provider behavior. (Light guard: router must not
        # import the amazon provider module.)
        router_path = (
            Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "marketplaces.py"
        )
        text = router_path.read_text(encoding="utf-8")
        assert "providers.amazon" not in text
