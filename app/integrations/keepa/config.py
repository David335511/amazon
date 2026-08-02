"""Keepa API configuration.

Design decisions:
- API key is stored in an environment variable (KEEPA_API_KEY), never in code.
- Rate limits are configurable per plan tier (defaults to the lowest tier).
- All settings have sensible defaults and can be overridden via env vars.
"""

from __future__ import annotations

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeepaConfig(BaseSettings):
    """Configuration for the Keepa API integration.

    Settings are loaded from environment variables with the KEEPA_ prefix,
    falling back to defaults suitable for the lowest API plan tier.
    """

    api_key: str = Field(
        default="",
        validation_alias="KEEPA_API_KEY",
        description="Keepa API key (store in environment variable, never in code)",
    )
    base_url: str = Field(
        default="https://api.keepa.com",
        validation_alias="KEEPA_BASE_URL",
        description="Keepa API base URL",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        validation_alias="KEEPA_MAX_RETRIES",
        description="Maximum number of retry attempts on failure",
    )
    retry_base_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        validation_alias="KEEPA_RETRY_BASE_DELAY",
        description="Base delay in seconds for exponential backoff",
    )
    retry_max_delay: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        validation_alias="KEEPA_RETRY_MAX_DELAY",
        description="Maximum delay in seconds between retries",
    )
    requests_per_minute: int = Field(
        default=20,
        ge=1,
        le=300,
        validation_alias="KEEPA_REQUESTS_PER_MINUTE",
        description="API rate limit: max requests per minute",
    )
    cache_ttl_seconds: int = Field(
        default=300,
        ge=0,
        le=86400,
        validation_alias="KEEPA_CACHE_TTL",
        description="Default cache TTL in seconds (0 = no caching)",
    )
    request_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        validation_alias="KEEPA_REQUEST_TIMEOUT",
        description="HTTP request timeout in seconds",
    )
    default_domain: str = Field(
        default="com",
        validation_alias="KEEPA_DEFAULT_DOMAIN",
        description="Default Amazon domain (com, co.uk, de, etc.)",
    )

    model_config = SettingsConfigDict(extra="ignore", frozen=False)

    @property
    def is_configured(self) -> bool:
        """Check if the API key is configured."""
        return bool(self.api_key)

    @property
    def min_request_interval(self) -> float:
        """Minimum time between requests in seconds to stay within rate limit."""
        return 60.0 / self.requests_per_minute
