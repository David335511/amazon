"""Dependency injection container and shared dependencies.

Design decisions:
- FastAPI's dependency injection system is used for all service/resolution.
- A `Container` class provides factory methods for services and repositories.
- This keeps wiring in one place and makes testing easy (override deps).
- The container is initialized at startup with the async session factory.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.browser import BrowserAutomationConfig, BrowserManager, Crawler
from app.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.documents import (
    DocumentConfig,
    DocumentManager,
    DocumentRepository,
    build_extractors,
    build_ocr_provider,
)
from app.domain.services.order_service import OrderService
from app.domain.services.product_service import ProductService
from app.events import EventBus, EventBusConfig, InMemoryEventBus
from app.experiments import (
    ExperimentConfig,
    ExperimentManager,
    ExperimentRepository,
)
from app.features import FeatureConfig, FeatureManager, FeatureRepository, build_signal_provider
from app.finance import (
    FinanceConfig,
    FinanceManager,
    FinanceRepository,
)
from app.forecasting import (
    ForecastConfig,
    ForecastingManager,
    ForecastingRepository,
    build_models,
)
from app.i18n import I18nConfig, I18nManager, I18nRepository
from app.infrastructure.repositories.order_repository import OrderRepository
from app.infrastructure.repositories.product_repository import ProductRepository
from app.knowledge_graph import (
    KnowledgeGraphConfig,
    KnowledgeGraphManager,
    PostgresGraphStore,
)
from app.learning import LearningConfig, LearningManager, LearningRepository
from app.marketplaces.manager import MarketplaceManager
from app.memory import (
    InMemoryVectorStore,
    MemoryConfig,
    MemoryManager,
    MemoryRepository,
    build_embedding_provider,
)
from app.multiagent import (
    MemorySharing,
    MultiAgentConfig,
    MultiAgentManager,
    MultiAgentRepository,
)
from app.multiagent.engine_tools import ReverseSourceTool, SupplierScoresTool
from app.plugins.manager import PluginManager
from app.reverse_sourcing import (
    PassthroughAsinResolver,
    PluginManagerProvider,
    ReverseSourcingConfig,
    ReverseSourcingManager,
    ReverseSourcingRepository,
    TrendDiscountPredictor,
)
from app.supplier_intel import (
    SupplierIntelConfig,
    SupplierIntelManager,
    SupplierIntelRepository,
)
from app.vision import VisionConfig, VisionManager, build_vision_provider

logger = get_logger(__name__)


# Marketplace manager is intentionally created once at import and lazily
# initialized (async) on first use. Providers are stateless across requests
# aside from the shared HTTP client, so a single shared instance is safe.
_marketplace_manager = MarketplaceManager()
_initialized = False


# Browser manager / crawler are shared singletons, built lazily on first use.
# The browser is only launched (Playwright + Chromium) when a supplier actually
# calls `crawler.fetch()` — so an unconfigured deployment never spawns a browser.
_browser_manager: BrowserManager | None = None

def get_browser_manager() -> BrowserManager:
    """Return the shared BrowserManager built from app config.

    The manager is inert until `.launch()` (which only happens inside
    `Crawler.fetch()`), so this is cheap even when browser automation is off.
    """
    global _browser_manager
    if _browser_manager is None:
        bcfg = BrowserAutomationConfig.model_validate(settings.browser)
        _browser_manager = BrowserManager(bcfg.browser)
    return _browser_manager


def get_crawler() -> Crawler:
    """Return a shared Crawler backed by the shared BrowserManager.

    Supplier plugins use this instead of implementing browser automation
    themselves. The crawler provides rate limiting, retries, CAPTCHA detection,
    proxy rotation, sessions, cookies, screenshots, and HTML archiving.
    """
    return Crawler(get_browser_manager())



async def get_marketplace_manager() -> MarketplaceManager:
    """Return the shared, initialized MarketplaceManager.

    This is the ONLY entry point the rest of the platform uses to talk to
    marketplaces. Callers receive the `MarketplaceManager` (which yields only
    `MarketplaceProvider` interface objects), never a concrete provider.
    """
    global _initialized
    if not _initialized:
        await _marketplace_manager.initialize()
        _initialized = True
    return _marketplace_manager


# Event bus is a shared in-process singleton. It is inert until someone calls
# publish()/subscribe(); background workers and distributed brokers are opt-in
# and never started automatically.
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return the shared, in-process event bus.

    This is the ONLY way modules should exchange async signals. Producers call
    ``bus.publish(...)`` and consumers subscribe with ``bus.subscribe(...)`` —
    decoupling them so no module needs to know who (if anyone) reacts.
    """
    global _event_bus
    if _event_bus is None:
        cfg = EventBusConfig.model_validate(settings.event_bus)
        _event_bus = InMemoryEventBus(
            default_max_retries=cfg.default_max_retries,
            backoff_base_ms=cfg.backoff_base_ms,
            backoff_max_ms=cfg.backoff_max_ms,
            jitter=cfg.jitter,
        )
    return _event_bus


# Vision subsystem singleton. The provider and config are stateless and shared.
# The manager exposes the ONLY way the platform analyzes images and matches
# products (vision + catalog fusion).
_vision_manager: VisionManager | None = None


def get_vision_manager() -> VisionManager:
    """Return the shared `VisionManager` built from app config.

    The provider is inert until an image is actually analyzed, so this is cheap
    even when a provider other than the pure-stdlib local default is configured.
    """
    global _vision_manager
    if _vision_manager is None:
        cfg = VisionConfig.model_validate(settings.vision)
        _vision_manager = VisionManager(provider=build_vision_provider(cfg), config=cfg)
    return _vision_manager


# Document intelligence system. The extractor map and OCR provider are shared
# and stateless; a new manager is built per request with the DB session.
_document_config: Any | None = None
_document_extractors: Any | None = None
_document_ocr: Any | None = None


def get_document_manager(
    db: AsyncSession = Depends(get_db),
) -> DocumentManager:
    """Build a `DocumentManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to parse, store
    and search documents (manuals, spec sheets, invoices).
    """
    global _document_config, _document_extractors, _document_ocr
    if _document_config is None:
        _document_config = DocumentConfig.model_validate(settings.documents)
    if _document_extractors is None:
        _document_extractors = build_extractors(_document_config)
    if _document_ocr is None:
        _document_ocr = build_ocr_provider(_document_config)
    repo = DocumentRepository(db)
    return DocumentManager(
        repo,
        config=_document_config,
        extractors=_document_extractors,
        ocr_provider=_document_ocr,
    )


# Memory system singletons. The embedding provider and vector store are shared
# and stateless; a new manager is built per request with the DB session. The
# manager exposes the ONLY way the rest of the platform stores/recalls memories.
_memory_config: MemoryConfig | None = None
_memory_embedding_provider: Any | None = None
_memory_vector_store: Any | None = None


def _get_memory_config() -> MemoryConfig:
    global _memory_config
    if _memory_config is None:
        _memory_config = MemoryConfig.model_validate(settings.memory)
    return _memory_config


def get_memory_manager(
    db: AsyncSession = Depends(get_db),
) -> MemoryManager:
    """Build a MemoryManager bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to store and
    recall AI memories (purchases, favorites, preferences, conversations, ...).
    """
    global _memory_embedding_provider, _memory_vector_store
    cfg = _get_memory_config()
    if _memory_embedding_provider is None:
        _memory_embedding_provider = build_embedding_provider(cfg)
    if _memory_vector_store is None:
        _memory_vector_store = InMemoryVectorStore()
    repo = MemoryRepository(db)
    return MemoryManager(
        repo,
        embedding_provider=_memory_embedding_provider,
        vector_store=_memory_vector_store,
        config=cfg,
    )



# Feature engineering system. The feature config and signal provider are shared
# and stateless; a new manager is built per request with the DB session.
_feature_config: Any | None = None
_feature_signal_provider: Any | None = None


def get_feature_manager(
    db: AsyncSession = Depends(get_db),
) -> FeatureManager:
    """Build a `FeatureManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to compute,
    store, refresh and retrieve engineered feature values.
    """
    global _feature_config, _feature_signal_provider
    if _feature_config is None:
        _feature_config = FeatureConfig.model_validate(settings.feature_store)
    if _feature_signal_provider is None:
        _feature_signal_provider = build_signal_provider(_feature_config)
    repo = FeatureRepository(db)
    return FeatureManager(
        repo,
        config=_feature_config,
        signal_provider=_feature_signal_provider,
    )


# Forecasting system. The forecast config and model registry are shared and
# stateless; a new manager is built per request with the DB session.
_forecast_config: Any | None = None
_forecast_models: Any | None = None


def get_forecasting_manager(
    db: AsyncSession = Depends(get_db),
) -> ForecastingManager:
    """Build a `ForecastingManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to forecast
    price / ROI / profit / inventory / sales / Buy Box / competition.
    """
    global _forecast_config, _forecast_models
    if _forecast_config is None:
        _forecast_config = ForecastConfig.model_validate(settings.forecasting)
    if _forecast_models is None:
        _forecast_models = build_models(_forecast_config)
    repo = ForecastingRepository(db)
    return ForecastingManager(
        repo,
        config=_forecast_config,
        models=_forecast_models,
    )


# Financial optimization engine. The config is shared and stateless; a new
# manager is built per request with the DB session.
_finance_config: Any | None = None


def get_finance_manager(
    db: AsyncSession = Depends(get_db),
) -> FinanceManager:
    """Build a `FinanceManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to track cash
    and optimize capital allocation / ordering.
    """
    global _finance_config
    if _finance_config is None:
        _finance_config = FinanceConfig.model_validate(settings.finance)
    repo = FinanceRepository(db)
    return FinanceManager(repo, config=_finance_config)


# Supplier intelligence. The config is shared and stateless; a new manager is
# built per request with the DB session.
_supplier_intel_config: Any | None = None


def get_supplier_intel_manager(
    db: AsyncSession = Depends(get_db),
) -> SupplierIntelManager:
    """Build a `SupplierIntelManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to record
    historical supplier observations and compute supplier scores / explanations.
    """
    global _supplier_intel_config
    if _supplier_intel_config is None:
        _supplier_intel_config = SupplierIntelConfig.model_validate(settings.supplier_intel)
    repo = SupplierIntelRepository(db)
    return SupplierIntelManager(repo, config=_supplier_intel_config)


# Reverse sourcing. Config + provider + resolver + predictor are shared and
# stateless; the intel manager and repo are built per request with the session.
_reverse_config: Any | None = None
_reverse_provider: Any | None = None
_reverse_resolver: Any | None = None
_reverse_predictor: Any | None = None
_reverse_intel_config: Any | None = None


def get_reverse_sourcing_manager(
    db: AsyncSession = Depends(get_db),
) -> ReverseSourcingManager:
    """Build a `ReverseSourcingManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to reverse-source
    an ASIN across every known supplier and generate sourcing recommendations.
    """
    global _reverse_config, _reverse_provider, _reverse_resolver, _reverse_predictor
    global _reverse_intel_config
    if _reverse_config is None:
        _reverse_config = ReverseSourcingConfig.model_validate(settings.reverse_sourcing)
    if _reverse_provider is None:
        _reverse_provider = PluginManagerProvider(PluginManager())
    if _reverse_resolver is None:
        _reverse_resolver = PassthroughAsinResolver()
    if _reverse_predictor is None:
        _reverse_predictor = TrendDiscountPredictor()
    if _reverse_intel_config is None:
        _reverse_intel_config = SupplierIntelConfig.model_validate(settings.supplier_intel)
    intel = SupplierIntelManager(SupplierIntelRepository(db), config=_reverse_intel_config)
    repo = ReverseSourcingRepository(db)
    return ReverseSourcingManager(
        repo,
        config=_reverse_config,
        provider=_reverse_provider,
        resolver=_reverse_resolver,
        predictor=_reverse_predictor,
        intel_manager=intel,
    )


# Multi-agent orchestration framework. Config is shared and stateless; a new
# manager is built per request with the DB session, binding the reverse-sourcing
# and supplier-intel engines as agent tools and the AI memory system as the
# durable memory-sharing backend.
_multiagent_config: Any | None = None


def get_multiagent_manager(
    db: AsyncSession = Depends(get_db),
) -> MultiAgentManager:
    """Build a `MultiAgentManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to run and
    introspect multi-agent pipelines.
    """
    global _multiagent_config
    if _multiagent_config is None:
        _multiagent_config = MultiAgentConfig.model_validate(settings.multiagent)
    repo = MultiAgentRepository(db)
    tools = [
        ReverseSourceTool(ReverseSourcingManager(
            ReverseSourcingRepository(db),
            config=ReverseSourcingConfig.model_validate(settings.reverse_sourcing),
            provider=PluginManagerProvider(PluginManager()),
        )),
        SupplierScoresTool(SupplierIntelManager(
            SupplierIntelRepository(db),
            config=SupplierIntelConfig.model_validate(settings.supplier_intel),
        )),
    ]
    return MultiAgentManager(
        repo,
        tools=tools,
        memory_sharing=MemorySharing(),
        config=_multiagent_config,
    )


# Experimentation platform. The config is shared and stateless; a new manager is
# built per request with the DB session.
_experiment_config: Any | None = None


def get_experiment_manager(
    db: AsyncSession = Depends(get_db),
) -> ExperimentManager:
    """Build an `ExperimentManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to run
    reproducible experiments (A/B, feature flags, prompts, rules, scoring / LLM /
    supplier / prediction comparisons) and generate experiment reports.
    """
    global _experiment_config
    if _experiment_config is None:
        _experiment_config = ExperimentConfig.model_validate(settings.experiments)
    repo = ExperimentRepository(db)
    return ExperimentManager(repo, config=_experiment_config)


# Commerce knowledge graph. The config is shared and stateless; a new manager is
# built per request with the DB session. The PostgresGraphStore backs the GraphStore
# interface; a future graph DB can be swapped in here without touching the API.
_knowledge_graph_config: Any | None = None


def get_knowledge_graph_manager(
    db: AsyncSession = Depends(get_db),
) -> KnowledgeGraphManager:
    """Build a `KnowledgeGraphManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to model and query
    the commerce knowledge graph (traversal, semantic search, related entities,
    recommendations, profitable clusters, hidden opportunities, reasoning).
    """
    global _knowledge_graph_config
    if _knowledge_graph_config is None:
        _knowledge_graph_config = KnowledgeGraphConfig.model_validate(settings.knowledge_graph)
    store = PostgresGraphStore(db)
    return KnowledgeGraphManager(store, config=_knowledge_graph_config)


# Continuous-learning platform. The config is shared and stateless; a new
# manager is built per request with the DB session.
_learning_config: Any | None = None
# Internationalization config (shared, stateless).
_i18n_config: Any | None = None


def get_learning_manager(
    db: AsyncSession = Depends(get_db),
) -> LearningManager:
    """Build a `LearningManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to record
    predictions, feed back outcomes, measure accuracy over time, detect issues,
    auto-tune rules/features, and run versioned continuous-learning cycles.
    """
    global _learning_config
    if _learning_config is None:
        _learning_config = LearningConfig.model_validate(settings.learning)
    repo = LearningRepository(db)
    return LearningManager(repo, config=_learning_config)


def get_i18n_manager(
    db: AsyncSession = Depends(get_db),
) -> I18nManager:
    """Build an `I18nManager` bound to the request's DB session.

    This is the ONLY entry point the rest of the platform uses to resolve
    languages, translate text, format locale values, switch languages (with
    browser + database + user-profile persistence) and validate translations.
    """
    global _i18n_config
    if _i18n_config is None:
        _i18n_config = I18nConfig.model_validate(settings.i18n)
    repo = I18nRepository(db)
    return I18nManager(repo, config=_i18n_config, session=db)


class Container:
    """Dependency injection container.

    Provides factory methods for creating services and repositories.
    Each factory receives its dependencies via constructor injection.
    """

    @staticmethod
    def product_repository(db: AsyncSession) -> ProductRepository:
        """Create a ProductRepository instance."""
        return ProductRepository(db)

    @staticmethod
    def order_repository(db: AsyncSession) -> OrderRepository:
        """Create an OrderRepository instance."""
        return OrderRepository(db)

    @staticmethod
    def product_service(repo: ProductRepository) -> ProductService:
        """Create a ProductService instance."""
        return ProductService(repo)

    @staticmethod
    def order_service(repo: OrderRepository) -> OrderService:
        """Create an OrderService instance."""
        return OrderService(repo)


# ──────────────────────────────────────────────────────────────
# Convenience dependencies
# ──────────────────────────────────────────────────────────────


async def get_product_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[ProductService, Any]:
    """Dependency that yields a ProductService with a DB session."""
    repo = ProductRepository(db)
    yield ProductService(repo)


async def get_order_service(
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[OrderService, Any]:
    """Dependency that yields an OrderService with a DB session."""
    repo = OrderRepository(db)
    yield OrderService(repo)


def get_request_id(request: Request) -> str:
    """Extract or generate a request ID from the incoming request."""
    return request.headers.get("X-Request-Id", "")
