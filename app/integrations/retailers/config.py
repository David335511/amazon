"""Retailer (Walmart / Home Depot) product data configuration.

Design decisions:
- Uses SerpApi's free tier (100 searches/month) as the transport for retailer
  product data, since neither Walmart nor Home Depot offers a free public API.
- The API key is stored in an environment variable (SERPAPI_API_KEY), never in code.
- Rate limits default to the free tier; all settings can be overridden via env vars.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RetailerConfig(BaseSettings):
    """Configuration for the retailer product data integration.

    Settings load from environment variables with the SERPAPI_ prefix,
    falling back to free-tier-friendly defaults.
    """

    api_key: str = Field(
        default="",
        validation_alias="SERPAPI_API_KEY",
        description="SerpApi API key (store in environment variable, never in code)",
    )
    base_url: str = Field(
        default="https://serpapi.com/search",
        validation_alias="SERPAPI_BASE_URL",
        description="SerpApi search endpoint (engine selected per provider)",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=10,
        validation_alias="SERPAPI_MAX_RETRIES",
        description="Maximum retry attempts on failure",
    )
    retry_base_delay: float = Field(
        default=0.5,
        ge=0.1,
        le=60.0,
        validation_alias="SERPAPI_RETRY_BASE_DELAY",
        description="Base delay in seconds for exponential backoff",
    )
    retry_max_delay: float = Field(
        default=10.0,
        ge=1.0,
        le=300.0,
        validation_alias="SERPAPI_RETRY_MAX_DELAY",
        description="Maximum delay in seconds between retries",
    )
    requests_per_minute: int = Field(
        default=10,
        ge=1,
        le=300,
        validation_alias="SERPAPI_REQUESTS_PER_MINUTE",
        description="API rate limit: max requests per minute",
    )
    monthly_budget: int = Field(
        default=250,
        ge=0,
        validation_alias="SERPAPI_MONTHLY_BUDGET",
        description=(
            "SerpApi searches available per calendar month. Lookups are paced "
            "against this budget by the scheduler and refused once exhausted."
        ),
    )
    monitor_products: str = Field(
        default="",
        validation_alias="SERPAPI_MONITOR_PRODUCTS",
        description=(
            "Comma-separated products the refresh scheduler should keep fresh, "
            "each as '<provider>:<product_id>', e.g. "
            "'walmart:10291024,home_depot:203202930'. Empty = scheduler runs "
            "but refreshes nothing."
        ),
    )
    scheduler_interval: int = Field(
        default=21600,
        ge=300,
        validation_alias="SERPAPI_SCHEDULER_INTERVAL",
        description=(
            "Seconds between retailer refresh cycles (default 6 hours). The "
            "monthly budget is spread across the month regardless."
        ),
    )
    cache_ttl_seconds: int = Field(
        default=3600,
        ge=0,
        le=86400,
        validation_alias="SERPAPI_CACHE_TTL",
        description="Default cache TTL in seconds (0 = no caching)",
    )
    request_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        validation_alias="SERPAPI_REQUEST_TIMEOUT",
        description="HTTP request timeout in seconds",
    )
    default_country: str = Field(
        default="us",
        validation_alias="SERPAPI_DEFAULT_COUNTRY",
        description="Default marketplace country code (us, ca, mx, ...)",
    )

    model_config = SettingsConfigDict(extra="ignore", frozen=False)

    @property
    def is_configured(self) -> bool:
        """Check if the API key is configured."""
        return bool(self.api_key)

    @property
    def min_request_interval(self) -> float:
        """Minimum time between requests to stay within the rate limit."""
        return 60.0 / self.requests_per_minute
