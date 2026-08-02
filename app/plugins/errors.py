"""Standardized error types for the plugin system.

All supplier-specific errors are wrapped into these types before
they propagate outside the plugin boundary.
"""


class PluginError(Exception):
    """Base exception for all plugin errors."""

    def __init__(self, message: str, supplier_code: str = "") -> None:
        self.supplier_code = supplier_code
        super().__init__(f"[{supplier_code}] {message}" if supplier_code else message)


class PluginNotFoundError(PluginError):
    """Raised when a plugin is not found in the registry."""

    def __init__(self, supplier_code: str) -> None:
        super().__init__(f"Plugin not found: {supplier_code}", supplier_code)


class PluginMethodNotImplementedError(PluginError):
    """Raised when a plugin does not implement a required method."""

    def __init__(self, supplier_code: str, method: str) -> None:
        super().__init__(f"Method '{method}' not implemented by {supplier_code}", supplier_code)


class PluginAuthenticationError(PluginError):
    """Raised when authentication with the supplier fails."""

    def __init__(self, supplier_code: str, message: str = "Authentication failed") -> None:
        super().__init__(message, supplier_code)


class PluginRateLimitError(PluginError):
    """Raised when the supplier API rate limit is exceeded."""

    def __init__(self, supplier_code: str, retry_after: int = 0) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s", supplier_code)


class PluginRequestError(PluginError):
    """Raised when a request to the supplier API fails."""

    def __init__(self, supplier_code: str, message: str = "Request failed") -> None:
        super().__init__(message, supplier_code)


class PluginParseError(PluginError):
    """Raised when parsing supplier response data fails."""

    def __init__(self, supplier_code: str, message: str = "Failed to parse response") -> None:
        super().__init__(message, supplier_code)
