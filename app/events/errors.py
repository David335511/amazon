"""Exception hierarchy for the internal event bus.

Mirrors the error-hierarchy pattern used by the marketplace layer: a small base
class plus specific subtypes, so callers can handle known failures while a
generic `EventBusError` catches everything else.
"""

from __future__ import annotations


class EventBusError(Exception):
    """Base error for all event-bus failures."""


class EventBusClosedError(EventBusError):
    """Raised when publishing/subscribing after the bus has been closed."""


class EventBusNotStartedError(EventBusError):
    """Raised when using background publishing before workers are started."""


class EventBusNotSubscribedError(EventBusError):
    """Raised when unsubscribing a subscription that is no longer active."""


class EventHandlerError(EventBusError):
    """Raised by a handler to signal a terminal, non-retryable failure.

    Unlike an unhandled exception (which the bus retries and then dead-letters),
    raising this from a handler makes the bus skip retries and route the event
    straight to the dead letter queue.
    """
