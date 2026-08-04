"""Runtime registry for the shared retailer service, budget, and scheduler.

Design decisions:
- Mirrors ``app.core.redis``: a module-level holder for app-wide singletons
  that are initialized once at startup and used by both the background refresh
  scheduler and the API routes. This keeps the scheduler and the request path on
  the *same* SerpApi client and monthly budget (shared Redis counters), so
  on-demand lookups and scheduled refreshes cannot double-spend the quota.
- All accessors return ``None`` when the runtime was not configured (e.g. the
  SerpApi key is absent, or in unit tests), so callers can fall back safely.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.integrations.retailers.budget import RetailerBudget
from app.integrations.retailers.scheduler import RetailerRefreshJob
from app.integrations.retailers.service import RetailerService

logger = get_logger(__name__)

_retailer_service: RetailerService | None = None
_retailer_budget: RetailerBudget | None = None
_retailer_job: RetailerRefreshJob | None = None


def configure_retailer_runtime(
    service: RetailerService,
    budget: RetailerBudget,
    job: RetailerRefreshJob | None = None,
) -> None:
    """Register the shared retailer runtime (called once at app startup)."""
    global _retailer_service, _retailer_budget, _retailer_job
    _retailer_service = service
    _retailer_budget = budget
    _retailer_job = job


def get_retailer_service() -> RetailerService | None:
    """Return the shared RetailerService, or None if not configured."""
    return _retailer_service


def get_retailer_budget() -> RetailerBudget | None:
    """Return the shared RetailerBudget, or None if not configured."""
    return _retailer_budget


def get_retailer_job() -> RetailerRefreshJob | None:
    """Return the shared RetailerRefreshJob, or None if not running."""
    return _retailer_job


async def shutdown_retailer_runtime() -> None:
    """Stop the shared scheduler (called at app shutdown)."""
    global _retailer_job
    if _retailer_job is not None:
        try:
            await _retailer_job.stop()
            logger.info("Retailer refresh scheduler stopped")
        except Exception as exc:
            logger.warning("Error stopping retailer scheduler: %s", exc)
        _retailer_job = None
