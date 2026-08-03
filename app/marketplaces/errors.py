"""Standardized error types for the marketplace abstraction layer.

Design decisions:
- Every marketplace-specific failure is wrapped into these types before it
  crosses the `MarketplaceProvider` boundary, so no marketplace-specific
  exception type ever leaks into the rest of the platform.
- The platform catches only `MarketplaceError` and its subclasses.
- A `marketplace_code` is attached to every error for logging/metrics.
"""

from __future__ import annotations


class MarketplaceError(Exception):
    """Base exception for all marketplace errors."""

    def __init__(self, message: str, marketplace_code: str = "") -> None:
        self.marketplace_code = marketplace_code
        super().__init__(f"[{marketplace_code}] {message}" if marketplace_code else message)


class MarketplaceNotFoundError(MarketplaceError):
    """Raised when a marketplace provider is not found in the registry."""

    def __init__(self, marketplace_code: str) -> None:
        super().__init__(f"Marketplace provider not found: {marketplace_code}", marketplace_code)


class MarketplaceNotEnabledError(MarketplaceError):
    """Raised when an operation is attempted on a disabled marketplace."""

    def __init__(self, marketplace_code: str) -> None:
        super().__init__(f"Marketplace is not enabled: {marketplace_code}", marketplace_code)


class MarketplaceMethodNotImplementedError(MarketplaceError):
    """Raised when a provider does not implement a required method.

    NOTE: This should never surface in normal operation because every
    provider inherits a graceful ``supported=False`` default. It exists as a
    defensive guard for the interface contract.
    """

    def __init__(self, marketplace_code: str, method: str) -> None:
        super().__init__(
            f"Method '{method}' not implemented by {marketplace_code}",
            marketplace_code,
        )
        self.method = method


class MarketplaceAuthenticationError(MarketplaceError):
    """Raised when authentication with the marketplace fails."""

    def __init__(self, marketplace_code: str, message: str = "Authentication failed") -> None:
        super().__init__(message, marketplace_code)


class MarketplaceRateLimitError(MarketplaceError):
    """Raised when a marketplace API rate limit is exceeded."""

    def __init__(self, marketplace_code: str, retry_after: int = 0) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s", marketplace_code)


class MarketplaceRequestError(MarketplaceError):
    """Raised when a request to a marketplace API fails."""

    def __init__(self, marketplace_code: str, message: str = "Request failed") -> None:
        super().__init__(message, marketplace_code)


class MarketplaceParseError(MarketplaceError):
    """Raised when parsing a marketplace response fails."""

    def __init__(self, marketplace_code: str, message: str = "Failed to parse response") -> None:
        super().__init__(message, marketplace_code)


class MarketplaceConfigurationError(MarketplaceError):
    """Raised when a marketplace is used without the required configuration."""

    def __init__(self, marketplace_code: str, message: str = "Marketplace misconfigured") -> None:
        super().__init__(message, marketplace_code)
