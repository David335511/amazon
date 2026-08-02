"""FastAPI application factory and global configuration.

Design decisions:
- `create_app()` factory function allows creating multiple app instances (e.g., for testing).
- Lifespan handlers manage async resource initialization and cleanup.
- Global exception handlers translate domain exceptions to consistent HTTP responses.
- CORS middleware is configured from settings.
- OpenAPI docs are conditionally enabled based on feature flags.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import router as v1_router
from app.config import settings
from app.core.database import close_db, init_db
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, init_redis
from app.core.telemetry import configure_telemetry
from app.domain.services.order_service import (
    InvalidOrderStatusTransitionError,
    OrderNotFoundError,
)
from app.domain.services.product_service import (
    InsufficientStockError,
    ProductASINConflictError,
    ProductNotFoundError,
)

logger = get_logger(__name__)

# Global analytics scheduler reference
_analytics_scheduler: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, Any]:
    """Application lifespan: initialize and clean up resources."""
    global _analytics_scheduler

    # Startup
    configure_logging()
    logger.info(
        "Starting Amazon AI Commerce Platform",
        env=settings.app.log_level,
        debug=settings.app.debug,
    )

    await init_db()
    logger.info("Database connection pool initialized")

    await init_redis()
    logger.info("Redis connection pool initialized")

    configure_telemetry(app)
    logger.info("OpenTelemetry configured")

    # Start analytics scheduler
    try:
        from app.analytics import AnalyticsScheduler
        from app.analytics.repository import AnalyticsRepository
        from app.analytics.service import AnalyticsService
        from app.core.database import async_session_factory

        if async_session_factory is not None:
            session = async_session_factory()
            repo = AnalyticsRepository(session)
            svc = AnalyticsService(repository=repo)
            scheduler = AnalyticsScheduler(
                service=svc,
                full_collection_interval=3600,  # 1 hour
                batch_size=50,
            )
            scheduler.start()
            _analytics_scheduler = scheduler
            logger.info("Analytics scheduler started")
    except Exception as exc:
        logger.warning("Failed to start analytics scheduler: %s", exc)

    yield

    # Shutdown
    await close_db()
    logger.info("Database connection pool closed")

    await close_redis()
    logger.info("Redis connection pool closed")

    # Stop analytics scheduler
    if _analytics_scheduler is not None:
        try:
            await _analytics_scheduler.stop()
            logger.info("Analytics scheduler stopped")
        except Exception as exc:
            logger.warning("Error stopping analytics scheduler: %s", exc)
        _analytics_scheduler = None

    logger.info("Amazon AI Commerce Platform shut down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A fully configured FastAPI instance.
    """
    app = FastAPI(
        title=settings.app.name,
        description="Production-quality AI commerce platform",
        version="0.1.0",
        docs_url="/docs" if settings.features.enable_swagger else None,
        redoc_url="/redoc" if settings.features.enable_swagger else None,
        lifespan=lifespan,
    )

    # ── Middleware ──────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors.get("allowed_origins", ["*"]),
        allow_credentials=settings.app.cors.get("allow_credentials", True),
        allow_methods=settings.app.cors.get("allow_methods", ["*"]),
        allow_headers=settings.app.cors.get("allow_headers", ["*"]),
    )

    # ── Routers ─────────────────────────────────────────────
    app.include_router(v1_router)

    # ── Dashboard ────────────────────────────────────────────
    _mount_dashboard(app)

    # ── Global Exception Handlers ───────────────────────────
    _register_exception_handlers(app)

    return app


def _mount_dashboard(app: FastAPI) -> None:
    """Mount the web dashboard."""
    from pathlib import Path

    # Serve dashboard HTML at root
    dashboard_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
    if dashboard_path.exists():
        @app.get("/", include_in_schema=False, response_class=HTMLResponse)
        async def dashboard(request: Request) -> HTMLResponse:
            return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))

        @app.get("/dashboard", include_in_schema=False, response_class=HTMLResponse)
        async def dashboard_alt(request: Request) -> HTMLResponse:
            return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))


def _register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers for domain exceptions."""

    @app.exception_handler(ProductNotFoundError)
    async def product_not_found_handler(
        _request: Request,
        exc: ProductNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "product_not_found",
                "message": str(exc),
                "product_id": str(exc.product_id),
            },
        )

    @app.exception_handler(ProductASINConflictError)
    async def product_asin_conflict_handler(
        _request: Request,
        exc: ProductASINConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "asin_conflict",
                "message": str(exc),
                "asin": exc.asin,
            },
        )

    @app.exception_handler(InsufficientStockError)
    async def insufficient_stock_handler(
        _request: Request,
        exc: InsufficientStockError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "insufficient_stock",
                "message": str(exc),
                "product_id": str(exc.product_id),
                "requested": exc.requested,
                "available": exc.available,
            },
        )

    @app.exception_handler(OrderNotFoundError)
    async def order_not_found_handler(
        _request: Request,
        exc: OrderNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "order_not_found",
                "message": str(exc),
                "order_id": str(exc.order_id),
            },
        )

    @app.exception_handler(InvalidOrderStatusTransitionError)
    async def invalid_status_handler(
        _request: Request,
        exc: InvalidOrderStatusTransitionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "invalid_status_transition",
                "message": str(exc),
                "current_status": exc.current,
                "target_status": exc.target,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred",
            },
        )


# ── Application Entry Point ─────────────────────────────────
app = create_app()
