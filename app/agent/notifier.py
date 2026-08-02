"""Notification system for the autonomous sourcing agent.

Design decisions:
- Supports multiple channels: in-app, email, webhook.
- Notifications are created for high-scoring opportunities and errors.
- Rate-limited to avoid notification spam.
- Async — notifications don't block the pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agent.models import DecisionAction, DecisionLog
from app.core.logging import get_logger

logger = get_logger(__name__)


class Notifier:
    """Sends notifications for agent decisions and events.

    Usage:
        notifier = Notifier()
        await notifier.notify_opportunity(decision)
        await notifier.notify_error("Supplier scan failed", error_details)
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        min_score_to_notify: float = 60.0,
    ) -> None:
        self._webhook_url = webhook_url
        self._min_score = min_score_to_notify
        self._last_notification: dict[str, datetime] = {}

    async def notify_opportunity(self, decision: DecisionLog) -> None:
        """Send a notification for a high-scoring opportunity."""
        if decision.action != DecisionAction.BUY:
            return
        if (decision.opportunity_score or 0) < self._min_score:
            return

        # Rate limit: max 1 notification per product per hour
        product_key = f"product:{decision.asin or decision.supplier_sku}"
        last = self._last_notification.get(product_key)
        if last and (datetime.now(timezone.utc) - last).total_seconds() < 3600:
            return
        self._last_notification[product_key] = datetime.now(timezone.utc)

        title = f"🟢 BUY Opportunity: {decision.product_title or decision.asin or 'Unknown'}"
        message = (
            f"Score: {decision.opportunity_score:.0f}/100 | "
            f"ROI: {decision.roi_percentage:.1f}% | "
            f"Profit: ${decision.net_profit:.2f}/unit | "
            f"Sales: {decision.monthly_sales:,}/mo"
        )

        logger.info("NOTIFICATION: %s — %s", title, message)
        await self._send_webhook(title, message, decision)

    async def notify_watch(self, decision: DecisionLog) -> None:
        """Send a notification for a watchlist opportunity."""
        if decision.action != DecisionAction.WATCH:
            return

        title = f"🟡 WATCH: {decision.product_title or decision.asin or 'Unknown'}"
        message = (
            f"Score: {decision.opportunity_score:.0f}/100 — "
            f"Has potential but needs monitoring"
        )

        logger.info("NOTIFICATION: %s — %s", title, message)
        await self._send_webhook(title, message, decision)

    async def notify_error(self, context: str, details: str) -> None:
        """Send a notification for an error."""
        logger.error("AGENT ERROR: %s — %s", context, details)
        await self._send_webhook(
            f"🔴 Agent Error: {context}",
            details,
            None,
        )

    async def notify_cycle_complete(
        self,
        cycle_count: int,
        products_processed: int,
        decisions_made: int,
        duration_seconds: float,
    ) -> None:
        """Send a notification when a cycle completes."""
        logger.info(
            "CYCLE %d COMPLETE: %d products, %d decisions in %.1fs",
            cycle_count, products_processed, decisions_made, duration_seconds,
        )

    async def _send_webhook(
        self,
        title: str,
        message: str,
        decision: DecisionLog | None,
    ) -> None:
        """Send a webhook notification if configured."""
        if not self._webhook_url:
            return
        try:
            import httpx
            payload = {
                "title": title,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "decision": decision.model_dump() if decision else None,
            }
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(self._webhook_url, json=payload)
        except Exception as exc:
            logger.warning("Webhook notification failed: %s", exc)
