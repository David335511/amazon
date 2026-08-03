"""Reverse sourcing facade.

`ReverseSourcingManager` is the ONLY entry point for reverse-sourcing an ASIN,
retrieving stored runs, and inspecting historical supplier series. It wires the
pluggable seams (supplier provider, ASIN resolver, discount predictor, supplier
intelligence) and delegates each run to the engine.
"""

from __future__ import annotations

from uuid import UUID

from app.plugins.manager import PluginManager
from app.reverse_sourcing.config import ReverseSourcingConfig
from app.reverse_sourcing.engine import ReverseSourcingEngine
from app.reverse_sourcing.errors import (
    ReverseSourcingNotFoundError,
    ReverseSourcingValidationError,
)
from app.reverse_sourcing.predictor import DiscountPredictor, TrendDiscountPredictor
from app.reverse_sourcing.provider import PluginManagerProvider, SupplierProvider
from app.reverse_sourcing.repository import ReverseSourcingRepository
from app.reverse_sourcing.resolver import AsinResolver, PassthroughAsinResolver
from app.reverse_sourcing.schemas import (
    HistoricalSupplierRead,
    ReverseSourcingCapabilities,
    ReverseSourcingList,
    ReverseSourcingRead,
    ReverseSourcingRequest,
    ReverseSourcingRunRead,
    ReverseSourcingStats,
)
from app.supplier_intel.manager import SupplierIntelManager


class ReverseSourcingManager:
    """Facade for reverse sourcing."""

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
        self._provider = provider or PluginManagerProvider(PluginManager())
        self._resolver = resolver or PassthroughAsinResolver()
        self._predictor = predictor or TrendDiscountPredictor()
        self._intel = intel_manager

    # ── Introspection ──────────────────────────────────────────────────────

    def capabilities(self) -> ReverseSourcingCapabilities:
        return ReverseSourcingCapabilities(
            enabled=self._config.enabled,
            suppliers=self._provider.enabled_suppliers(),
            max_suppliers=self._config.max_suppliers,
            features={
                "forecast_horizon": self._config.forecast_horizon,
                "currency": self._config.default_currency,
            },
        )

    # ── Source ─────────────────────────────────────────────────────────────

    async def source(self, request: ReverseSourcingRequest) -> ReverseSourcingRead:
        if not request.asin:
            raise ReverseSourcingValidationError("ASIN must not be empty")
        engine = ReverseSourcingEngine(
            repository=self._repo,
            config=self._config,
            provider=self._provider,
            resolver=self._resolver,
            predictor=self._predictor,
            intel_manager=self._intel,
        )
        return await engine.source(request)

    # ── Retrieve runs ──────────────────────────────────────────────────────

    async def get_run(self, run_id: UUID) -> ReverseSourcingRunRead:
        row = await self._repo.get_run(run_id)
        if row is None:
            raise ReverseSourcingNotFoundError(f"Reverse-sourcing run {run_id} not found")
        return ReverseSourcingRunRead.from_row(row)

    async def list_runs(
        self,
        *,
        asin: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ReverseSourcingList:
        rows, total = await self._repo.list_runs(asin=asin, limit=limit, offset=offset)
        return ReverseSourcingList(
            items=[ReverseSourcingRunRead.from_row(r) for r in rows], total=total
        )

    async def historical(
        self, supplier_code: str, asin: str
    ) -> HistoricalSupplierRead | None:
        data = await self._repo.historical_for_supplier(supplier_code, asin)
        if data is None:
            raise ReverseSourcingNotFoundError(
                f"No historical offers for supplier {supplier_code!r} on ASIN {asin}"
            )
        return HistoricalSupplierRead(supplier_code=supplier_code, **data)

    # ── Stats ──────────────────────────────────────────────────────────────

    async def stats(self) -> ReverseSourcingStats:
        return ReverseSourcingStats(**await self._repo.stats())
