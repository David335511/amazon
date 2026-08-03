"""Distributed message-broker seam for the event bus.

Today the platform runs as a single process, so the `InMemoryEventBus` delivers
events in-process. This module defines the `MessageBroker` transport contract so
the bus can later scale to multiple instances/processes WITHOUT changing how
domain code publishes or subscribes.

Design decisions:
- `MessageBroker` is the ONLY contract the bus depends on for cross-instance
  delivery. It is topic-based (topic == `EventType.value`).
- `InMemoryBroker` is a correct, testable in-process implementation — the
  default when the platform is deployed as a single service.
- `RedisStreamsBroker` is a production-ready Redis Streams implementation for
  when the platform is scaled horizontally. It is selected via config
  (`event_bus.broker_type: redis`) and disabled by default.
- Future brokers (Kafka, RabbitMQ, NATS, SQS, ...) implement the same protocol.
"""

from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any


class MessageBroker(ABC):
    """Transport contract for delivering serialized event bytes by topic."""

    @abstractmethod
    async def publish(self, topic: str, message: bytes) -> None:
        """Publish a serialized message to a topic."""

    @abstractmethod
    def subscribe(self, topic: str) -> AsyncIterator[bytes]:
        """Yield serialized messages published to a topic."""

    @abstractmethod
    async def health(self) -> bool:
        """Report broker connectivity."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release broker resources."""


class InMemoryBroker(MessageBroker):
    """In-process broker using per-topic asyncio queues.

    Correct for single-process deployments and unit tests; no network involved.
    """

    def __init__(self) -> None:
        self._topics: dict[str, list[asyncio.Queue[bytes]]] = defaultdict(list)
        self._closed = False

    async def publish(self, topic: str, message: bytes) -> None:
        if self._closed:
            msg = "InMemoryBroker is closed"
            raise RuntimeError(msg)
        for queue in list(self._topics.get(topic, ())):
            queue.put_nowait(message)

    async def subscribe(self, topic: str) -> AsyncIterator[bytes]:
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._topics[topic].append(queue)
        try:
            while not self._closed:
                yield await queue.get()
        finally:
            if queue in self._topics[topic]:
                self._topics[topic].remove(queue)

    async def health(self) -> bool:
        return not self._closed

    async def aclose(self) -> None:
        self._closed = True


class RedisStreamsBroker(MessageBroker):
    """Redis Streams based broker for horizontally-scaled deployments.

    Uses consumer groups so multiple bus instances can each receive a copy of
    every event (fan-out) with at-least-once delivery and explicit acks.

    Not exercised by the unit suite (requires a live Redis), so it is selected
    explicitly via ``event_bus.broker_type = redis``.
    """

    def __init__(
        self,
        *,
        redis_client: Any,
        stream_prefix: str = "events",
        group_prefix: str = "platform",
        consumer_id: str = "worker",
        block_ms: int = 2000,
        batch_size: int = 10,
    ) -> None:
        self._redis = redis_client
        self._stream_prefix = stream_prefix
        self._group_prefix = group_prefix
        self._consumer = consumer_id
        self._block_ms = block_ms
        self._batch = batch_size

    def _stream(self, topic: str) -> str:
        return f"{self._stream_prefix}:{topic}"

    def _group(self, topic: str) -> str:
        return f"{self._group_prefix}:{topic}"

    async def publish(self, topic: str, message: bytes) -> None:
        await self._redis.xadd(self._stream(topic), {"data": message})

    async def subscribe(self, topic: str) -> AsyncIterator[bytes]:
        stream = self._stream(topic)
        group = self._group(topic)
        with contextlib.suppress(Exception):
            # Group may already exist — this is the normal concurrent case.
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
        while True:
            response = await self._redis.xreadgroup(
                group,
                self._consumer,
                {stream: ">"},
                count=self._batch,
                block=self._block_ms,
            )
            if not response:
                continue
            for _stream_name, entries in response:
                for message_id, fields in entries:
                    yield fields[b"data"]
                    await self._redis.xack(stream, group, message_id)

    async def health(self) -> bool:
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    async def aclose(self) -> None:
        # The redis client is owned by the app's connection pool, not the broker.
        return None
