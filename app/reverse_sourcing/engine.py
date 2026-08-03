"""Reverse-sourcing engine.

Turns an Amazon ASIN into a full supplier analysis. It is fully provider-driven:

- It talks ONLY to a `SupplierProvider` (never to a plugin directly), so adding
  a supplier plugin (a file in ``app/plugins/suppliers/``) requires **no engine
  change**.
- It uses a pluggable `AsinResolver` (default passthrough), a pluggable
  `DiscountPredictor` (default stdlib trend), and an optional
  `SupplierIntelManager` for supplier reliability / risk / confidence.
- It persists each run + per-supplier offer, so repeated runs accumulate the
  **historical** price / discount series per (supplier, ASIN).

The engine orchestrates; `app.reverse_sourcing.scoring` owns all pure math.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.reverse_sourcing.config import ReverseSourcingConfig
from app.reverse_sourcing.errors import ReverseSourcingNotFoundError
from app.reverse_sourcing.offer import Offer
from app.reverse_sourcing.predictor import DiscountPredictor, TrendDiscountPredictor
from app.reverse_sourcing.provider import SupplierProvider
from app.reverse_sourcing.repository import ReverseSourcingRepository
from app.reverse_sourcing.resolver import AsinResolver, PassthroughAsinResolver
from app.reverse_sourcing.schemas import (
    HistoricalSupplierRead,
    RankedSupplierRead,
    ReverseSourcingRead,
    SupplierHighlightRead,
    SupplierOfferRead,
)
from app.reverse_sourcing.scoring import build_summary, highlights, rank_offers, recommendations
from app.supplier_intel.manager import SupplierIntelManager


class ReverseSourcingEngine:
    """Orchestrates a single reverse-sourcing run for an ASIN."""

    def __init__(
        self,
        repository: ReverseSourcingRepository,
        config: ReverseSourcingConfig | None = None,
        provider: SupplierProvider | None = None,
        resolver: AsinResolver | None = None,
        predictor: DiscountPredictor | None = None,
        intel_manager: SupplierIntelManager | None = None,
    ) -> None:
        self._repo = repository
        self._config = config or ReverseSourcingConfig()
        self._provider = provider
        self._resolver = resolver or PassthroughAsinResolver()
        self._predictor = predictor or TrendDiscountPredictor()
        self._intel = intel_manager

    # ── Main entry ─────────────────────────────────────────────────────────

    async def source(self, request: Any) -> ReverseSourcingRead:
        identity = await self._resolver.resolve(request.asin, request.upc)
        if identity is None:
            raise ReverseSourcingNotFoundError(f"ASIN {request.asin} not found")

        offers = await self._gather_offers(identity, request.quantity, request.postal_code)
        offers = offers[: self._config.max_suppliers]

        intel = await self._intel_scores([o.supplier_code for o in offers])
        historical = await self._historical(identity.asin, offers)

        predicted: dict[str, float | None] = {}
        for o in offers:
            hist = historical.get(o.supplier_code)
            predicted[o.supplier_code] = self._predictor.predict(
                o.supplier_code, identity.asin, hist.discounts if hist else []
            )

        ranking, _scores = rank_offers(offers, intel, self._config.rank_weights)
        hls = highlights(offers, ranking, intel)
        recs = recommendations(offers, hls, predicted, intel)
        summary_text = build_summary(identity.asin, ranking, hls)

        await self._persist(
            identity=identity,
            request=request,
            offers=offers,
            predicted=predicted,
            ranking=ranking,
            highlights=hls,
            summary=summary_text,
        )

        return ReverseSourcingRead(
            asin=identity.asin,
            upc=identity.upc,
            title=identity.title,
            quantity=request.quantity,
            postal_code=request.postal_code,
            currency=request.currency,
            offers=[self._to_offer_read(o, predicted) for o in offers],
            historical=historical,
            ranking=[RankedSupplierRead(**r) for r in ranking],
            highlights={k: SupplierHighlightRead(**v) for k, v in hls.items()},
            predicted_discounts=predicted,
            recommendations=recs,
            summary=summary_text,
            created_at=datetime.now(UTC),
        )

    # ── Offer gathering ────────────────────────────────────────────────────

    async def _gather_offers(self, identity, quantity: int, postal_code: str | None) -> list[Offer]:
        if self._provider is None:
            return []
        offers: list[Offer] = []
        query = identity.upc or identity.asin
        for code in self._provider.enabled_suppliers():
            try:
                offer = await self._gather_one(code, identity, query, quantity, postal_code)
                if offer is not None:
                    offers.append(offer)
            except Exception:
                continue
        return offers

    async def _gather_one(
        self,
        code: str,
        identity,
        query: str,
        quantity: int,
        postal_code: str | None,
    ) -> Offer | None:
        assert self._provider is not None
        found = await self._provider.find_product(code, query, identity.upc)
        if found is None or not found.supplier_sku:
            return None
        sku = found.supplier_sku

        unit_price = float(found.price or 0)
        moq = int(found.moq or 1)
        in_stock = bool(found.in_stock)
        stock_status = "in_stock" if in_stock else "unknown"
        delivery_days = found.estimated_delivery_days

        try:
            pricing = await self._provider.pricing(code, sku)
            if pricing and pricing.unit_price:
                unit_price = float(pricing.unit_price)
        except Exception:
            pass
        try:
            availability = await self._provider.availability(code, sku)
            if availability:
                in_stock = availability.is_available
                stock_status = availability.stock_status
        except Exception:
            pass

        shipping_cost = 0.0
        shipping_days = delivery_days or 0
        try:
            shipping = await self._provider.shipping(code, sku, quantity, postal_code)
            if shipping and shipping.methods:
                method = min(shipping.methods, key=lambda m: float(m.get("cost", 0)))
                shipping_cost = float(method.get("cost", 0.0))
                shipping_days = int(method.get("days", shipping_days))
        except Exception:
            pass

        current_discount = 0.0
        try:
            coupons = await self._provider.coupon(code)
            current_discount = max(
                [self._coupon_depth(c, unit_price) for c in coupons],
                default=0.0,
            )
        except Exception:
            pass

        landed_cost = unit_price * quantity + shipping_cost
        return Offer(
            supplier_code=code,
            supplier_name=code,
            supplier_sku=sku,
            unit_price=round(unit_price, 2),
            currency="USD",
            shipping_cost=round(shipping_cost, 2),
            shipping_days=shipping_days,
            landed_cost=round(landed_cost, 2),
            in_stock=in_stock,
            stock_status=stock_status,
            moq=max(moq, 1),
            current_discount=round(current_discount, 4),
        )

    # ── Intel / historical / prediction helpers ────────────────────────────

    async def _intel_scores(self, codes: list[str]) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        if self._intel is None:
            return out
        for code in codes:
            try:
                scores = await self._intel.scores(code)
                rel = scores.get("reliability")
                risk = scores.get("risk")
                out[code] = {
                    "reliability": rel.value if rel else 0.5,
                    "risk": risk.value if risk else 0.5,
                    "confidence": rel.confidence if rel else 0.0,
                }
            except Exception:
                continue
        return out

    async def _historical(self, asin: str, offers: list[Offer]) -> dict[str, HistoricalSupplierRead]:
        out: dict[str, HistoricalSupplierRead] = {}
        for o in offers:
            data = await self._repo.historical_for_supplier(o.supplier_code, asin)
            if data:
                out[o.supplier_code] = HistoricalSupplierRead(
                    supplier_code=o.supplier_code,
                    sample_count=data["sample_count"],
                    prices=data["prices"],
                    discounts=data["discounts"],
                    avg_price=data["avg_price"],
                    avg_discount=data["avg_discount"],
                )
        return out

    async def _persist(
        self,
        *,
        identity,
        request,
        offers: list[Offer],
        predicted: dict[str, float | None],
        ranking: list[dict[str, Any]],
        highlights: dict[str, dict[str, Any]],
        summary: str,
    ) -> None:
        rank_by_code = {r["supplier_code"]: r["rank"] for r in ranking}
        offer_rows = []
        for o in offers:
            offer_rows.append(
                {
                    "supplier_code": o.supplier_code,
                    "supplier_name": o.supplier_name,
                    "supplier_sku": o.supplier_sku,
                    "unit_price": o.unit_price,
                    "currency": o.currency,
                    "shipping_cost": o.shipping_cost,
                    "shipping_days": o.shipping_days,
                    "landed_cost": o.landed_cost,
                    "in_stock": o.in_stock,
                    "stock_status": o.stock_status,
                    "moq": o.moq,
                    "current_discount": o.current_discount,
                    "predicted_discount": predicted.get(o.supplier_code),
                    "rank": rank_by_code.get(o.supplier_code, 0),
                }
            )
        await self._repo.create_run(
            asin=identity.asin,
            upc=identity.upc,
            title=identity.title,
            quantity=request.quantity,
            postal_code=request.postal_code,
            currency=request.currency,
            best_supplier=(highlights.get("best") or {}).get("supplier_code"),
            cheapest_supplier=(highlights.get("cheapest") or {}).get("supplier_code"),
            fastest_supplier=(highlights.get("fastest") or {}).get("supplier_code"),
            highest_confidence_supplier=(highlights.get("highest_confidence") or {}).get("supplier_code"),
            summary=summary,
            offers=offer_rows,
        )

    @staticmethod
    def _to_offer_read(o: Offer, predicted: dict[str, float | None]) -> SupplierOfferRead:
        return SupplierOfferRead(
            supplier_code=o.supplier_code,
            supplier_name=o.supplier_name,
            supplier_sku=o.supplier_sku,
            unit_price=o.unit_price,
            currency=o.currency,
            shipping_cost=o.shipping_cost,
            shipping_days=o.shipping_days,
            landed_cost=o.landed_cost,
            in_stock=o.in_stock,
            stock_status=o.stock_status,
            moq=o.moq,
            current_discount=o.current_discount,
            predicted_discount=predicted.get(o.supplier_code),
        )

    @staticmethod
    def _coupon_depth(coupon, unit_price: float) -> float:
        try:
            if coupon.discount_type == "percentage":
                depth = float(coupon.discount_value) / 100.0
            elif coupon.discount_type == "fixed_amount":
                depth = float(coupon.discount_value) / max(unit_price, 1e-9)
            else:
                depth = 0.0
        except Exception:
            depth = 0.0
        return max(0.0, min(1.0, depth))
