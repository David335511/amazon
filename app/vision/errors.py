"""Vision subsystem exceptions.

Hierarchy mirrors the rest of the platform: a single base class with specific
subclasses so callers can catch narrowly (e.g. a bad upload) or broadly
(any vision failure).
"""

from __future__ import annotations


class VisionError(Exception):
    """Base class for all vision subsystem errors."""


class VisionDecodeError(VisionError):
    """Raised when an image cannot be decoded from bytes."""


class VisionValidationError(VisionError):
    """Raised when a vision request is malformed (e.g. missing inputs)."""


class VisionUnsupportedError(VisionError):
    """Raised when a requested capability requires an unavailable provider."""
