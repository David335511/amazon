"""Per-marketplace configuration management.

Each marketplace provider gets its own configuration loaded from YAML or
environment variables. Configs are validated at startup by Pydantic.

Design decisions:
- Credentials are placeholders by default and should be supplied via
  environment variables / secrets, never committed.
- Every marketplace can be enabled/disabled independently.
- `extra` holds marketplace-specific options (e.g. eBay OAuth scopes,
  TikTok shop region) without widening the shared schema.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MarketplaceConfig(BaseModel):
    """Configuration for a single marketplace provider."""

    code: str = Field(..., description="Marketplace code (e.g. 'amazon')")
    name: str = Field(..., description="Display name")
    enabled: bool = Field(default=True, description="Is this marketplace enabled?")
    api_key: str = Field(default="", description="API key / client id")
    api_secret: str = Field(default="", description="API secret / client secret")
    access_token: str = Field(default="", description="OAuth access token")
    refresh_token: str = Field(default="", description="OAuth refresh token")
    base_url: str = Field(default="", description="API base URL")
    store_id: str = Field(default="", description="Seller/store/merchant identifier")
    max_retries: int = Field(default=3, ge=0, le=10, description="Max retry attempts")
    request_timeout: int = Field(default=30, ge=5, le=120, description="Request timeout")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Marketplace-specific extra configuration",
    )

    @property
    def is_configured(self) -> bool:
        """True if at least one credential is present."""
        return bool(self.api_key or self.access_token or self.refresh_token)


class MarketplaceProviderConfig(BaseModel):
    """Root configuration for all marketplace providers."""

    marketplaces: dict[str, MarketplaceConfig] = Field(
        default_factory=dict,
        description="Map of marketplace code to configuration",
    )
    default_timeout: int = Field(default=30, ge=5, le=120)
    default_retries: int = Field(default=3, ge=0, le=10)
