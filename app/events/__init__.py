"""Internal event bus.

Lets modules communicate through domain events instead of direct coupling.
A producer calls ``publish()``; any number of subscribers react via
``subscribe()`` — with retry, a dead letter queue, and priority ordering, plus
a clean seam (`MessageBroker`) for future distributed delivery.

Typical usage::

    bus = get_event_bus()
    sub = bus.subscribe(EventType.PRODUCT_CREATED, on_product_created)
    await bus.publish(ProductCreated(product_id="p1", title="Widget"))
    sub.unsubscribe()
"""

from app.events.broker import InMemoryBroker, MessageBroker, RedisStreamsBroker
from app.events.bus import BrokeredEventBus, EventBus, InMemoryEventBus, Subscription
from app.events.config import EventBusConfig
from app.events.dlq import DeadLetterQueue, DeadLetterRecord
from app.events.errors import (
    EventBusClosedError,
    EventBusError,
    EventBusNotStartedError,
    EventBusNotSubscribedError,
    EventHandlerError,
)
from app.events.models import (
    AIRecommendationCreated,
    BuyBoxChanged,
    CouponFound,
    Event,
    EventPriority,
    EventType,
    InventoryChanged,
    NotificationSent,
    OpportunityDetected,
    PriceChanged,
    ProductCreated,
    ProductMatched,
    SupplierUpdated,
    deserialize_event,
    event_registry,
    serialize_event,
)

__all__ = [
    "AIRecommendationCreated",
    "BrokeredEventBus",
    "BuyBoxChanged",
    "CouponFound",
    "DeadLetterQueue",
    "DeadLetterRecord",
    "Event",
    "EventBus",
    "EventBusClosedError",
    "EventBusConfig",
    "EventBusError",
    "EventBusNotStartedError",
    "EventBusNotSubscribedError",
    "EventHandlerError",
    "EventPriority",
    "EventType",
    "InMemoryBroker",
    "InMemoryEventBus",
    "InventoryChanged",
    "MessageBroker",
    "NotificationSent",
    "OpportunityDetected",
    "PriceChanged",
    "ProductCreated",
    "ProductMatched",
    "RedisStreamsBroker",
    "Subscription",
    "SupplierUpdated",
    "deserialize_event",
    "event_registry",
    "serialize_event",
]
