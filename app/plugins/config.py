"""Per-supplier configuration management.

Each supplier plugin gets its own configuration loaded from YAML
or environment variables. Configs are validated at startup.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SupplierConfig(BaseModel):
    """Configuration for a single supplier plugin."""

    code: str = Field(..., description="Supplier code (e.g., 'walmart')")
    name: str = Field(..., description="Display name")
    enabled: bool = Field(default=True, description="Is this supplier enabled?")
    api_key: str = Field(default="", description="API key for this supplier")
    api_secret: str = Field(default="", description="API secret for this supplier")
    base_url: str = Field(default="", description="API base URL")
    max_retries: int = Field(default=3, ge=0, le=10, description="Max retry attempts")
    request_timeout: int = Field(default=30, ge=5, le=120, description="Request timeout")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Supplier-specific extra configuration",
    )


class SupplierPluginConfig(BaseModel):
    """Root configuration for all supplier plugins."""

    suppliers: dict[str, SupplierConfig] = Field(
        default_factory=dict,
        description="Map of supplier code to configuration",
    )
    default_timeout: int = Field(default=30, ge=5, le=120)
    default_retries: int = Field(default=3, ge=0, le=10)
