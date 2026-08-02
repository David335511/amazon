"""V1 API router — aggregates all versioned route modules."""

from fastapi import APIRouter

from app.api.v1.agent import router as agent_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.assistant import router as assistant_router
from app.api.v1.health import router as health_router
from app.api.v1.i18n import router as i18n_router
from app.api.v1.orders import router as orders_router
from app.api.v1.products import router as products_router
from app.api.v1.products_sourcing import router as products_sourcing_router
from app.api.v1.sourcing import router as sourcing_router

router = APIRouter(prefix="/api/v1")

router.include_router(agent_router)
router.include_router(analytics_router)
router.include_router(assistant_router)
router.include_router(i18n_router)
router.include_router(health_router)
router.include_router(products_router)
router.include_router(orders_router)
router.include_router(products_sourcing_router)
router.include_router(sourcing_router)
