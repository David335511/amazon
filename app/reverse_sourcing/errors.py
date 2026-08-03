"""Exception hierarchy for reverse sourcing."""

from __future__ import annotations


class ReverseSourcingError(Exception):
    """Base class for all reverse-sourcing errors."""


class ReverseSourcingValidationError(ReverseSourcingError):
    """Raised for invalid inputs (empty ASIN, oversized batch, ...)."""


class ReverseSourcingNotFoundError(ReverseSourcingError):
    """Raised when the ASIN / run cannot be resolved."""
