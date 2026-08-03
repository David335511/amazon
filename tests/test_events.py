"""Tests for the internal event bus.

Verifies:
- Event registry (all 10 event types mapped, unique) and (de)serialization.
- publish() -> subscriber delivery; multiple subscribers; unsubscribe.
- Retry with exponential backoff (success after transient failures).
- Dead letter queue (permanent failure, terminal EventHandlerError, replay, purge).
- Priority ordering in the background workers.
- Priority filters on subscriptions.
- Lifecycle errors (closed bus, background-not-started).
- The distributed broker seam (BrokeredEventBus + InMemoryBroker).
- The DI entry point returns a shared InMemoryEventBus.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from app.events import (
    AIRecommendationCreated,
    BuyBoxChanged,
    CouponFound,
    Event,
    EventBusNotStartedError,
    EventHandlerError,
    EventPriority,
    EventType,
    InMemoryBroker,
    InMemoryEventBus,
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
from app.events.bus import BrokeredEventBus
from app.events.dlq import DeadLetterQueue, DeadLetterRecord
from app.events.errors import EventBusClosedError, EventBusError


def _sample_events() -> list[Event]:
    """One instance of every concrete event type."""
    return [
        PriceChanged(external_id="B0TEST", new_price=25.50),
        InventoryChanged(external_id="B0TEST", new_quantity=42),
        SupplierUpdated(supplier_code="walmart", supplier_name="Walmart", status="active"),
        CouponFound(supplier_code="target", sku="SKU1", coupon_code="SAVE10"),
        BuyBoxChanged(external_id="B0TEST", previous_winner="seller_a", winner="seller_b"),
        OpportunityDetected(external_id="B0TEST", marketplace="amazon", score=0.91),
        ProductMatched(supplier_sku="SKU1", external_id="B0TEST", match_score=0.98),
        ProductCreated(product_id="p-1", title="Widget"),
        AIRecommendationCreated(recommendation_id="r-1", kind="reprice"),
        NotificationSent(notification_id="n-1", channel="email", recipient="a@b.c"),
    ]


# ── Event registry & serialization ─────────────────────────


class TestEventRegistry:
    def test_all_ten_event_types_registered(self) -> None:
        reg = event_registry()
        assert len(reg) == 10
        assert set(reg) == set(EventType)

    def test_event_types_are_unique_and_stable(self) -> None:
        values = [et.value for et in EventType]
        assert len(values) == len(set(values))
        assert EventType.PRICE_CHANGED.value == "price.changed"
        assert EventType.NOTIFICATION_SENT.value == "notification.sent"

    def test_priority_values_are_ordered(self) -> None:
        assert EventPriority.CRITICAL < EventPriority.HIGH < EventPriority.NORMAL < EventPriority.LOW


class TestSerialization:
    @pytest.mark.parametrize("event", _sample_events(), ids=[e.event_type.value for e in _sample_events()])
    def test_roundtrip_preserves_payload(self, event: Event) -> None:
        raw = serialize_event(event)
        restored = deserialize_event(raw)
        assert restored.event_type == event.event_type
        assert restored.event_id == event.event_id
        assert restored.priority == event.priority
        assert type(restored) is type(event)

    def test_unknown_event_type_raises(self) -> None:
        with pytest.raises(EventBusError):
            deserialize_event(b'{"event_type": "not.real"}')


# ── Publish / subscribe ────────────────────────────────────


class TestPublishSubscribe:
    async def test_subscriber_receives_event(self) -> None:
        bus = InMemoryEventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.PRODUCT_CREATED, handler)
        event = ProductCreated(product_id="p-1", title="Widget")
        event_id = await bus.publish(event)

        assert event_id == event.event_id
        assert len(received) == 1
        assert received[0].product_id == "p-1"

    async def test_multiple_subscribers_all_receive(self) -> None:
        bus = InMemoryEventBus()
        seen: list[str] = []

        def a(_e: Event) -> None:
            seen.append("a")

        async def b(_e: Event) -> None:
            seen.append("b")

        bus.subscribe(EventType.PRICE_CHANGED, a)
        bus.subscribe(EventType.PRICE_CHANGED, b)
        await bus.publish(PriceChanged(external_id="x", new_price=10))

        assert sorted(seen) == ["a", "b"]

    async def test_unsubscribe_stops_delivery(self) -> None:
        bus = InMemoryEventBus()
        count = 0

        def handler(_e: Event) -> None:
            nonlocal count
            count += 1

        sub = bus.subscribe(EventType.COUPON_FOUND, handler)
        await bus.publish(CouponFound(supplier_code="t", sku="s", coupon_code="c"))
        sub.unsubscribe()
        await bus.publish(CouponFound(supplier_code="t", sku="s", coupon_code="c"))

        assert count == 1

    async def test_unrelated_event_not_delivered(self) -> None:
        bus = InMemoryEventBus()
        delivered = False

        async def handler(_e: Event) -> None:
            nonlocal delivered
            delivered = True

        bus.subscribe(EventType.INVENTORY_CHANGED, handler)
        await bus.publish(PriceChanged(external_id="x", new_price=1))
        assert not delivered

    async def test_publish_overrides_priority(self) -> None:
        bus = InMemoryEventBus()
        seen: list[EventPriority] = []

        async def handler(event: Event) -> None:
            seen.append(event.priority)

        bus.subscribe(EventType.SUPPLIER_UPDATED, handler)
        await bus.publish(
            SupplierUpdated(supplier_code="w", supplier_name="W", status="x"),
            priority=EventPriority.HIGH,
        )
        assert seen == [EventPriority.HIGH]

    async def test_publish_returns_unique_ids(self) -> None:
        bus = InMemoryEventBus()
        id1 = await bus.publish(ProductCreated(product_id="a"))
        id2 = await bus.publish(ProductCreated(product_id="b"))
        assert id1 != id2


# ── Retry ──────────────────────────────────────────────────


class TestRetry:
    async def test_transient_failure_then_success(self) -> None:
        bus = InMemoryEventBus(backoff_base_ms=1, backoff_max_ms=2, jitter=False)
        calls = 0

        async def handler(_event: Event) -> None:
            nonlocal calls
            calls += 1
            if calls < 3:
                msg = "flaky"
                raise RuntimeError(msg)

        bus.subscribe(
            EventType.PRODUCT_MATCHED,
            handler,
            max_retries=3,
            backoff_base_ms=1,
            backoff_max_ms=2,
            jitter=False,
        )
        await bus.publish(ProductMatched(supplier_sku="s", external_id="e", match_score=0.9))

        assert calls == 3  # 2 failures + 1 success
        assert bus.dead_letters.count() == 0

    async def test_exhausted_retries_dead_letters(self) -> None:
        bus = InMemoryEventBus(backoff_base_ms=1, backoff_max_ms=2, jitter=False)

        async def always_fails(_e: Event) -> None:
            msg = "boom"
            raise RuntimeError(msg)

        event = ProductCreated(product_id="p-x")
        bus.subscribe(
            EventType.PRODUCT_CREATED,
            always_fails,
            max_retries=2,
            backoff_base_ms=1,
            backoff_max_ms=2,
            jitter=False,
        )
        await bus.publish(event)

        assert bus.dead_letters.count() == 1
        record = bus.dead_letters.list()[0]
        assert record.event_id == event.event_id
        assert record.attempts == 3  # initial + 2 retries
        assert "boom" in record.error

    async def test_handler_error_skips_retry(self) -> None:
        bus = InMemoryEventBus()
        calls = 0

        async def handler(_e: Event) -> None:
            nonlocal calls
            calls += 1
            raise EventHandlerError("do not retry")

        bus.subscribe(EventType.NOTIFICATION_SENT, handler, max_retries=5)
        await bus.publish(NotificationSent(notification_id="n", channel="e", recipient="r"))

        assert calls == 1  # no retries despite max_retries=5
        assert bus.dead_letters.count() == 1


# ── Dead letter queue ──────────────────────────────────────


class TestDeadLetter:
    async def test_dlq_bounded_capacity(self) -> None:
        dlq = DeadLetterQueue(cap=3)
        for i in range(5):
            await dlq.put(
                DeadLetterRecord(
                    event_id=str(i),
                    event_type=EventType.PRODUCT_CREATED,
                    handler="h",
                    error="e",
                    attempts=1,
                    priority=EventPriority.NORMAL,
                    event=ProductCreated(product_id=str(i)),
                )
            )
        assert dlq.count() == 3
        assert dlq.list()[0].event_id == "4"  # newest first

    async def test_replay_dead_letters(self) -> None:
        bus = InMemoryEventBus(backoff_base_ms=1, backoff_max_ms=2, jitter=False)
        recovered: list[Event] = []
        calls = 0

        async def flaky(event: Event) -> None:
            # Call #1 (initial publish) fails; call #2 (replay) succeeds.
            nonlocal calls
            calls += 1
            if calls == 1:
                msg = "first time"
                raise RuntimeError(msg)
            recovered.append(event)

        event = ProductCreated(product_id="p-replay")
        bus.subscribe(
            EventType.PRODUCT_CREATED,
            flaky,
            max_retries=0,
            backoff_base_ms=1,
            backoff_max_ms=2,
            jitter=False,
        )
        await bus.publish(event)
        assert bus.dead_letters.count() == 1

        replayed = await bus.replay_dead_letters()
        assert replayed == 1
        assert bus.dead_letters.count() == 0
        assert recovered[0].product_id == "p-replay"

    async def test_purge_dead_letters_by_type(self) -> None:
        bus = InMemoryEventBus(backoff_base_ms=1, backoff_max_ms=2, jitter=False)

        async def fail(_e: Event) -> None:
            msg = "x"
            raise RuntimeError(msg)

        bus.subscribe(EventType.PRODUCT_CREATED, fail, max_retries=0)
        bus.subscribe(EventType.COUPON_FOUND, fail, max_retries=0)
        await bus.publish(ProductCreated(product_id="a"))
        await bus.publish(CouponFound(supplier_code="t", sku="s", coupon_code="c"))

        assert bus.dead_letters.count() == 2
        removed = await bus.purge_dead_letters(EventType.PRODUCT_CREATED)
        assert removed == 1
        assert bus.dead_letters.count() == 1


# ── Priority ───────────────────────────────────────────────


class TestPriority:
    async def test_background_workers_honor_priority(self) -> None:
        bus = InMemoryEventBus()
        await bus.start_background(num_workers=1)
        order: list[EventPriority] = []
        done = asyncio.Event()

        async def handler(event: Event) -> None:
            order.append(event.priority)
            if len(order) == 3:
                done.set()

        bus.subscribe(EventType.PRODUCT_CREATED, handler)
        # Enqueue LOW first, then HIGH, then CRITICAL.
        await bus.publish_async(
            ProductCreated(product_id="a"),
            priority=EventPriority.LOW,
        )
        await bus.publish_async(
            ProductCreated(product_id="b"),
            priority=EventPriority.HIGH,
        )
        await bus.publish_async(
            ProductCreated(product_id="c"),
            priority=EventPriority.CRITICAL,
        )

        await asyncio.wait_for(done.wait(), timeout=2)
        assert order == [EventPriority.CRITICAL, EventPriority.HIGH, EventPriority.LOW]
        await bus.aclose()

    async def test_publish_async_before_start_raises(self) -> None:
        bus = InMemoryEventBus()
        with pytest.raises(EventBusNotStartedError):
            await bus.publish_async(ProductCreated(product_id="a"))

    async def test_priority_filter(self) -> None:
        bus = InMemoryEventBus()
        seen: list[EventPriority] = []

        async def handler(event: Event) -> None:
            seen.append(event.priority)

        bus.subscribe(
            EventType.BUYBOX_CHANGED,
            handler,
            priority_filter={EventPriority.HIGH, EventPriority.CRITICAL},
        )
        await bus.publish(BuyBoxChanged(external_id="x", winner="w"), priority=EventPriority.HIGH)
        await bus.publish(BuyBoxChanged(external_id="x", winner="w"), priority=EventPriority.LOW)

        assert seen == [EventPriority.HIGH]


# ── Lifecycle / introspection ──────────────────────────────


class TestLifecycle:
    async def test_closed_bus_rejects_publish(self) -> None:
        bus = InMemoryEventBus()
        await bus.aclose()
        with pytest.raises(EventBusClosedError):
            await bus.publish(ProductCreated(product_id="a"))

    async def test_closed_bus_rejects_subscribe(self) -> None:
        bus = InMemoryEventBus()
        await bus.aclose()
        with pytest.raises(EventBusClosedError):
            bus.subscribe(EventType.PRODUCT_CREATED, lambda _: None)

    async def test_stats(self) -> None:
        bus = InMemoryEventBus()

        async def handler(_e: Event) -> None:
            pass

        bus.subscribe(EventType.PRODUCT_CREATED, handler)
        await bus.publish(ProductCreated(product_id="a"))
        stats = bus.stats()
        assert stats["publish_count"] == 1
        assert stats["subscriber_count"] == 1
        assert stats["dead_letter_count"] == 0
        assert stats["closed"] is False

    async def test_subscriber_count_per_type(self) -> None:
        bus = InMemoryEventBus()
        bus.subscribe(EventType.PRICE_CHANGED, lambda _: None)
        bus.subscribe(EventType.PRICE_CHANGED, lambda _: None)
        bus.subscribe(EventType.PRODUCT_CREATED, lambda _: None)
        assert bus.subscriber_count(EventType.PRICE_CHANGED) == 2
        assert bus.subscriber_count() == 3


# ── Distributed broker seam ────────────────────────────────


class TestBrokerSeam:
    async def test_brokered_bus_delivers_via_broker(self) -> None:
        local = InMemoryEventBus()
        broker = InMemoryBroker()
        bus = BrokeredEventBus(local=local, broker=broker, topics=[EventType.PRODUCT_CREATED])
        await bus.start()
        # Let the consumer task register its subscription before publishing.
        await asyncio.sleep(0.02)
        received: list[Event] = []
        done = asyncio.Event()

        async def handler(event: Event) -> None:
            received.append(event)
            done.set()

        bus.subscribe(EventType.PRODUCT_CREATED, handler)
        await bus.publish(ProductCreated(product_id="via-broker"))

        await asyncio.wait_for(done.wait(), timeout=2)
        assert received[0].product_id == "via-broker"
        await bus.aclose()

    async def test_in_memory_broker_roundtrip(self) -> None:
        broker = InMemoryBroker()
        assert await broker.health() is True

        got: list[bytes] = []

        async def consume() -> None:
            async for message in broker.subscribe("topic.x"):
                got.append(message)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        await broker.publish("topic.x", b"hello")
        await asyncio.sleep(0.01)
        assert got == [b"hello"]
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await broker.aclose()
        assert await broker.health() is False


# ── DI ─────────────────────────────────────────────────────


class TestDI:
    def test_shared_singleton(self) -> None:
        from app.core.dependencies import get_event_bus

        a = get_event_bus()
        b = get_event_bus()
        assert a is b
        assert isinstance(a, InMemoryEventBus)
