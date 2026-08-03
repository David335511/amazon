"""Domain event models for the internal event bus.

Design decisions:
- A single `Event` envelope carries identity, timing, correlation and priority.
  Each concrete event type adds its own typed payload fields. Events are
  Pydantic models so they serialize/deserialize cleanly — a prerequisite for
  pushing them through a distributed broker (Redis Streams, Kafka, ...) later.
- `EventType` is the routing key. Subscribers subscribe to an `EventType`
  (not a Python class), so the bus stays broker-friendly (topic == event value).
- `EventPriority` is an `IntEnum` where LOWER value = HIGHER priority. This
  matches `asyncio.PriorityQueue` semantics (pops the smallest first), so the
  same enum drives both synchronous ordering and background priority queues.
- Concrete event classes are auto-discovered through `event_registry()` so a
  new event type needs no wiring beyond defining its model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import IntEnum, StrEnum
from functools import lru_cache
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.events.errors import EventBusError


class EventPriority(IntEnum):
    """Priority of an event. Lower value = higher priority."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class EventType(StrEnum):
    """The set of domain event types the platform can emit."""

    PRICE_CHANGED = "price.changed"
    INVENTORY_CHANGED = "inventory.changed"
    SUPPLIER_UPDATED = "supplier.updated"
    COUPON_FOUND = "coupon.found"
    BUYBOX_CHANGED = "buybox.changed"
    OPPORTUNITY_DETECTED = "opportunity.detected"
    PRODUCT_MATCHED = "product.matched"
    PRODUCT_CREATED = "product.created"
    AI_RECOMMENDATION_CREATED = "ai.recommendation.created"
    NOTIFICATION_SENT = "notification.sent"


class Event(BaseModel):
    """Base envelope shared by every domain event.

    Concrete event types subclass this and declare their own typed payload
    fields. `extra="forbid"` enforces a tight schema so a mistyped field is
    caught at construction rather than silently dropped at the broker edge.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: str | None = None
    source: str = ""
    version: int = 1
    # Arbitrary extra key/value data; concrete events add typed fields too.
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── The concrete domain events ─────────────────────────────


class PriceChanged(Event):
    """A product's price changed on a marketplace."""

    event_type: EventType = EventType.PRICE_CHANGED
    external_id: str
    marketplace: str = "amazon"
    old_price: Decimal | None = None
    new_price: Decimal
    currency: str = "USD"


class InventoryChanged(Event):
    """A product's stock level changed on a marketplace."""

    event_type: EventType = EventType.INVENTORY_CHANGED
    external_id: str
    marketplace: str = "amazon"
    old_quantity: int | None = None
    new_quantity: int
    warehouse: str | None = None


class SupplierUpdated(Event):
    """A supplier's metadata or status changed."""

    event_type: EventType = EventType.SUPPLIER_UPDATED
    supplier_code: str
    supplier_name: str
    status: str
    change: str = ""


class CouponFound(Event):
    """A coupon was discovered for a supplier SKU."""

    event_type: EventType = EventType.COUPON_FOUND
    supplier_code: str
    sku: str
    coupon_code: str
    discount: Decimal | None = None
    expires_at: datetime | None = None


class BuyBoxChanged(Event):
    """The Buy Box / featured offer winner changed for a product."""

    event_type: EventType = EventType.BUYBOX_CHANGED
    external_id: str
    marketplace: str = "amazon"
    previous_winner: str | None = None
    winner: str
    price: Decimal | None = None


class OpportunityDetected(Event):
    """A sourcing opportunity was detected for a product."""

    event_type: EventType = EventType.OPPORTUNITY_DETECTED
    external_id: str
    marketplace: str
    score: float
    reason: str = ""
    estimated_profit: Decimal | None = None


class ProductMatched(Event):
    """A supplier product was matched to a known platform product."""

    event_type: EventType = EventType.PRODUCT_MATCHED
    supplier_sku: str
    external_id: str
    match_score: float
    matched_by: str = ""


class ProductCreated(Event):
    """A product was created in the platform catalog."""

    event_type: EventType = EventType.PRODUCT_CREATED
    product_id: str
    asin: str | None = None
    title: str = ""


class AIRecommendationCreated(Event):
    """An AI/agent generated a recommendation."""

    event_type: EventType = EventType.AI_RECOMMENDATION_CREATED
    recommendation_id: str
    kind: str
    summary: str = ""
    priority: EventPriority = EventPriority.NORMAL


class NotificationSent(Event):
    """A notification was delivered to a recipient."""

    event_type: EventType = EventType.NOTIFICATION_SENT
    notification_id: str
    channel: str
    recipient: str
    subject: str = ""


# ── Discovery + (de)serialization ──────────────────────────


@lru_cache(maxsize=1)
def event_registry() -> dict[EventType, type[Event]]:
    """Map every `EventType` to its concrete event class.

    Auto-discovers subclasses of `Event`, so adding a new event type requires
    nothing beyond defining the class. Mirrors the registry pattern used by the
    marketplace and plugin layers.
    """
    registry: dict[EventType, type[Event]] = {}
    for subclass in Event.__subclasses__():
        field = subclass.model_fields.get("event_type")
        default = field.default if field is not None else None
        if isinstance(default, EventType):
            registry[default] = subclass
    return registry


def serialize_event(event: Event) -> bytes:
    """Serialize an event to JSON bytes for transport (broker/DLQ)."""
    return event.model_dump_json().encode("utf-8")


def deserialize_event(data: bytes | str) -> Event:
    """Rehydrate an event from its serialized form.

    Resolves the concrete class via `event_type`, so the typed payload is
    validated exactly as it was when emitted.
    """
    payload = json.loads(data)
    try:
        event_type = EventType(payload["event_type"])
    except ValueError as exc:
        msg = f"Unknown event type: {payload.get('event_type')!r}"
        raise EventBusError(msg) from exc
    cls = event_registry().get(event_type)
    if cls is None:
        msg = f"Unknown event type: {event_type}"
        raise EventBusError(msg)
    return cls.model_validate(payload)
