"""V1 API router — aggregates all versioned route modules."""

from fastapi import APIRouter, Depends

from app.api.v1.agent import router as agent_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.assistant import router as assistant_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.i18n import router as i18n_router
from app.api.v1.marketplaces import router as marketplaces_router
from app.api.v1.memory import router as memory_router
from app.api.v1.orders import router as orders_router
from app.api.v1.products import router as products_router
from app.api.v1.products_sourcing import router as products_sourcing_router
from app.api.v1.sourcing import router as sourcing_router
from app.api.v1.vision import router as vision_router
from app.core.security import require_api_key

# The entire v1 API surface requires API-key auth by default. Health probes are
# exempt inside `require_api_key` via `SecurityConfig.public_paths`, and the
# dependency is a no-op when `security.enabled` is false (local dev).
router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

router.include_router(agent_router)
router.include_router(analytics_router)
router.include_router(assistant_router)
router.include_router(documents_router)
router.include_router(i18n_router)
router.include_router(marketplaces_router)
router.include_router(memory_router)
router.include_router(health_router)
router.include_router(products_router)
router.include_router(orders_router)
router.include_router(products_sourcing_router)
router.include_router(sourcing_router)
router.include_router(vision_router)
