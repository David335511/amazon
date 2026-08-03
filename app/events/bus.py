"""The internal event bus.

The `EventBus` is the ONLY way modules exchange async signals. It decouples
producers from consumers: a module emits a domain event via `publish()` and any
number of subscribers react — without the producer knowing who (if anyone)
listens.

Capabilities:
- publish() / subscribe()          — core routing by `EventType`.
- retry()                          — per-subscription exponential backoff + jitter
                                    on handler failure, with a dead-letter cap.
- dead letter queue                — failed deliveries retained for replay/purge.
- priority                         — `EventPriority` ordering; honored in both the
                                    synchronous path and the background workers.
- future distributed brokers       — optional `MessageBroker` transport; see
                                    `broker.py` and `BrokeredEventBus`.

Design decisions:
- Handlers are invoked with `await` (synchronous within publish) so ordering is
  deterministic and tests are reliable. Handlers should be fast; slow work
  should be delegated to the background queue (`publish_async`).
- Retry is per-subscription (max_retries, backoff, jitter, priority_filter), so
  a flaky analytics subscriber does not force a critical notifier to retry.
- An unhandled exception is retried then dead-lettered. Raising
  `EventHandlerError` skips retry and dead-letters immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.events.broker import MessageBroker
from app.events.dlq import DeadLetterQueue, DeadLetterRecord
from app.events.errors import (
    EventBusClosedError,
    EventBusNotStartedError,
    EventHandlerError,
)
from app.events.models import Event, EventPriority, EventType, deserialize_event

logger = logging.getLogger("amazon.events")

Handler = Callable[[Event], Any]


@dataclass
class HandlerEntry:
    """A registered subscriber plus its delivery policy."""

    handler: Handler
    max_retries: int = 3
    backoff_base_ms: int = 200
    backoff_max_ms: int = 5000
    jitter: bool = True
    priority_filter: set[EventPriority] | None = None
    active: bool = True

    def matches(self, priority: EventPriority) -> bool:
        """Whether this subscriber accepts an event of the given priority."""
        return self.priority_filter is None or priority in self.priority_filter


class Subscription:
    """Handle for an active subscription; used to unsubscribe."""

    def __init__(self, bus: EventBus, event_type: EventType, entry: HandlerEntry) -> None:
        self._bus = bus
        self._event_type = event_type
        self._entry = entry

    def unsubscribe(self) -> None:
        self._entry.active = False


class EventBus(ABC):
    """Contract for an internal event bus."""

    @abstractmethod
    async def publish(
        self,
        event: Event,
        *,
        priority: EventPriority | None = None,
    ) -> str:
        """Publish an event, returning its id."""

    @abstractmethod
    def subscribe(
        self,
        event_type: EventType,
        handler: Handler,
        *,
        max_retries: int | None = None,
        backoff_base_ms: int | None = None,
        backoff_max_ms: int | None = None,
        jitter: bool | None = None,
        priority_filter: set[EventPriority] | None = None,
    ) -> Subscription:
        """Subscribe a handler to an event type."""

    @abstractmethod
    async def aclose(self) -> None:
        """Shut down the bus and release resources."""


class InMemoryEventBus(EventBus):
    """In-process event bus with retry, dead-lettering and priority.

    The default bus for the current single-process platform. When constructed
    with a `broker`, publish routes through the broker and a background consumer
    re-delivers into local subscribers (see `BrokeredEventBus` for the managed
    wrapper) — the path to distributed delivery.
    """

    def __init__(
        self,
        *,
        dlq: DeadLetterQueue | None = None,
        broker: MessageBroker | None = None,
        default_max_retries: int = 3,
        backoff_base_ms: int = 200,
        backoff_max_ms: int = 5000,
        jitter: bool = True,
    ) -> None:
        self._dlq = dlq or DeadLetterQueue()
        self._broker = broker
        self._default_max_retries = default_max_retries
        self._default_backoff_base_ms = backoff_base_ms
        self._default_backoff_max_ms = backoff_max_ms
        self._default_jitter = jitter

        self._subscribers: dict[EventType, list[HandlerEntry]] = defaultdict(list)
        self._background_queue: asyncio.PriorityQueue[tuple[int, int, Event]] | None = None
        self._workers: list[asyncio.Task[Any]] = []
        self._next_seq = 0
        self._publish_count = 0
        self._closed = False

    # ── Subscription management ─────────────────────────────

    def subscribe(
        self,
        event_type: EventType,
        handler: Handler,
        *,
        max_retries: int | None = None,
        backoff_base_ms: int | None = None,
        backoff_max_ms: int | None = None,
        jitter: bool | None = None,
        priority_filter: set[EventPriority] | None = None,
    ) -> Subscription:
        if self._closed:
            msg = "Cannot subscribe to a closed event bus"
            raise EventBusClosedError(msg)
        entry = HandlerEntry(
            handler=handler,
            max_retries=max_retries if max_retries is not None else self._default_max_retries,
            backoff_base_ms=(
                backoff_base_ms if backoff_base_ms is not None else self._default_backoff_base_ms
            ),
            backoff_max_ms=(
                backoff_max_ms if backoff_max_ms is not None else self._default_backoff_max_ms
            ),
            jitter=jitter if jitter is not None else self._default_jitter,
            priority_filter=priority_filter,
        )
        self._subscribers[event_type].append(entry)
        return Subscription(self, event_type, entry)

    # ── Publishing ──────────────────────────────────────────

    async def publish(
        self,
        event: Event,
        *,
        priority: EventPriority | None = None,
    ) -> str:
        if priority is not None:
            event.priority = priority
        if self._broker is not None:
            # Distributed transport: hand off to the broker; local delivery is
            # handled by the broker consumer (see BrokeredEventBus).
            from app.events.models import serialize_event

            await self._broker.publish(event.event_type.value, serialize_event(event))
            return event.event_id
        await self._dispatch_local(event)
        return event.event_id

    async def publish_async(self, event: Event, *, priority: EventPriority | None = None) -> None:
        """Enqueue an event to be dispatched by background workers.

        Use for slow handlers so the publisher does not block. Requires
        `start_background()` first. Priorities are honored by the workers.
        """
        if self._background_queue is None:
            msg = "Background workers not started; call start_background() first"
            raise EventBusNotStartedError(msg)
        if priority is not None:
            event.priority = priority
        seq = self._next_seq
        self._next_seq += 1
        await self._background_queue.put((int(event.priority), seq, event))

    async def start_background(self, num_workers: int = 2) -> None:
        """Start background workers that drain the async priority queue."""
        if self._closed:
            msg = "Cannot start background workers on a closed event bus"
            raise EventBusClosedError(msg)
        if self._background_queue is not None:
            return
        self._background_queue = asyncio.PriorityQueue()
        for _ in range(num_workers):
            self._workers.append(asyncio.create_task(self._worker()))

    async def _worker(self) -> None:
        queue = self._background_queue
        while queue is not None:
            try:
                _, _, event = await queue.get()
            except asyncio.CancelledError:
                return
            await self._dispatch_local(event)
            queue.task_done()

    # ── Dispatch ────────────────────────────────────────────

    async def _dispatch_local(self, event: Event) -> None:
        if self._closed:
            msg = "Cannot publish to a closed event bus"
            raise EventBusClosedError(msg)
        for entry in list(self._subscribers.get(event.event_type, ())):
            if entry.active and entry.matches(event.priority):
                await self._deliver(entry, event)
        self._publish_count += 1

    async def _deliver(self, entry: HandlerEntry, event: Event) -> None:
        """Deliver to one handler with per-subscription retry + dead-lettering."""
        attempts = 0
        while True:
            attempts += 1
            try:
                result = entry.handler(event)
                if asyncio.iscoroutine(result):
                    await result
                return
            except EventHandlerError as exc:
                # Terminal failure: no retry, straight to the DLQ.
                await self._dead_letter(entry, event, exc, attempts)
                return
            except Exception as exc:  # retry any handler failure
                if attempts > entry.max_retries:
                    await self._dead_letter(entry, event, exc, attempts)
                    return
                await asyncio.sleep(self._backoff(entry, attempts))

    async def _dead_letter(
        self,
        entry: HandlerEntry,
        event: Event,
        exc: Exception,
        attempts: int,
    ) -> None:
        record = DeadLetterRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            handler=getattr(entry.handler, "__name__", entry.handler.__class__.__name__),
            error=f"{type(exc).__name__}: {exc}",
            attempts=attempts,
            failed_at=datetime.now(UTC),
            priority=event.priority,
            event=event,
        )
        await self._dlq.put(record)
        logger.warning(
            "Event dead-lettered after %s attempts: %s -> %s",
            attempts,
            event.event_type.value,
            record.handler,
        )

    @staticmethod
    def _backoff(entry: HandlerEntry, attempt: int) -> float:
        """Exponential backoff in seconds with optional jitter."""
        delay = min(entry.backoff_base_ms * (2 ** (attempt - 1)), entry.backoff_max_ms)
        if entry.jitter:
            delay = random.uniform(delay * 0.5, delay)
        return delay / 1000.0

    # ── Dead letter queue helpers ───────────────────────────

    @property
    def dead_letters(self) -> DeadLetterQueue:
        return self._dlq

    async def replay_dead_letters(self, event_type: EventType | None = None) -> int:
        """Re-publish retained dead-lettered events (optionally by type)."""
        records = [
            r for r in self._dlq.list() if event_type is None or r.event_type == event_type
        ]
        await self._dlq.purge(event_type)
        for record in records:
            await self.publish(record.event)
        return len(records)

    async def purge_dead_letters(self, event_type: EventType | None = None) -> int:
        return await self._dlq.purge(event_type)

    # ── Introspection / lifecycle ───────────────────────────

    def subscriber_count(self, event_type: EventType | None = None) -> int:
        if event_type is not None:
            return sum(1 for e in self._subscribers.get(event_type, ()) if e.active)
        return sum(sum(1 for e in entries if e.active) for entries in self._subscribers.values())

    def stats(self) -> dict[str, Any]:
        return {
            "publish_count": self._publish_count,
            "subscriber_count": self.subscriber_count(),
            "dead_letter_count": self._dlq.count(),
            "broker": type(self._broker).__name__ if self._broker else None,
            "closed": self._closed,
        }

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._workers.clear()
        if self._broker is not None:
            await self._broker.aclose()


class BrokeredEventBus(EventBus):
    """Bridge between local subscribers and a distributed `MessageBroker`.

    Demonstrates the future-distributed path: `publish` writes to the broker;
    a background consumer per topic deserializes and re-delivers to local
    subscribers through an `InMemoryEventBus` (which retains retry/DLQ/priority
    semantics). Multiple instances can subscribe to the same topics to fan out
    events across the fleet.
    """

    def __init__(
        self,
        *,
        local: InMemoryEventBus,
        broker: MessageBroker,
        topics: list[EventType] | None = None,
    ) -> None:
        self._local = local
        self._broker = broker
        self._topics = topics or [et for et in EventType]
        self._consumer_tasks: list[asyncio.Task[Any]] = []
        self._started = False

    async def start(self) -> None:
        """Begin consuming broker topics into the local bus."""
        if self._started:
            return
        self._started = True
        for topic in self._topics:
            self._consumer_tasks.append(asyncio.create_task(self._consume(topic.value)))

    async def _consume(self, topic: str) -> None:
        async for raw in self._broker.subscribe(topic):
            try:
                event = deserialize_event(raw)
            except Exception:  # skip corrupt broker messages
                logger.exception("Skipping undecodable event from broker topic %s", topic)
                continue
            await self._local.publish(event)

    async def publish(
        self,
        event: Event,
        *,
        priority: EventPriority | None = None,
    ) -> str:
        if priority is not None:
            event.priority = priority
        from app.events.models import serialize_event

        await self._broker.publish(event.event_type.value, serialize_event(event))
        return event.event_id

    def subscribe(
        self,
        event_type: EventType,
        handler: Handler,
        *,
        max_retries: int | None = None,
        backoff_base_ms: int | None = None,
        backoff_max_ms: int | None = None,
        jitter: bool | None = None,
        priority_filter: set[EventPriority] | None = None,
    ) -> Subscription:
        return self._local.subscribe(
            event_type,
            handler,
            max_retries=max_retries,
            backoff_base_ms=backoff_base_ms,
            backoff_max_ms=backoff_max_ms,
            jitter=jitter,
            priority_filter=priority_filter,
        )

    async def aclose(self) -> None:
        for task in self._consumer_tasks:
            task.cancel()
        for task in self._consumer_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._consumer_tasks.clear()
        await self._broker.aclose()
