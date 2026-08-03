"""Exception hierarchy for supplier intelligence."""

from __future__ import annotations


class SupplierIntelError(Exception):
    """Base class for all supplier-intelligence errors."""


class SupplierIntelValidationError(SupplierIntelError):
    """Raised for invalid inputs (empty supplier id, oversized batch, ...)."""


class SupplierIntelNotFoundError(SupplierIntelError):
    """Raised when there is no historical record for a supplier."""
