"""Configuration models for the browser automation framework.

Mirrors the plugin/marketplace config conventions: Pydantic models with
sensible defaults, validated at startup. The whole framework is driven by a
single `BrowserAutomationConfig` which contains per-concern sub-configs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FingerprintConfig(BaseModel):
    """Options for browser fingerprint randomization."""

    enabled: bool = Field(default=False)
    randomize_user_agent: bool = Field(default=True)
    randomize_viewport: bool = Field(default=False)
    viewport_width_min: int = Field(default=1024, ge=320)
    viewport_width_max: int = Field(default=1920, ge=320)
    viewport_height_min: int = Field(default=600, ge=300)
    viewport_height_max: int = Field(default=1200, ge=300)
    randomize_locale: bool = Field(default=True)
    locales: list[str] = Field(
        default_factory=lambda: ["en-US", "en-GB", "en-CA", "en-AU", "de-DE", "fr-FR"]
    )
    randomize_timezone: bool = Field(default=True)
    timezones: list[str] = Field(
        default_factory=lambda: [
            "America/New_York",
            "America/Los_Angeles",
            "America/Chicago",
            "Europe/London",
            "Europe/Berlin",
            "Asia/Tokyo",
        ]
    )
    randomize_device_scale_factor: bool = Field(default=True)


class ProxyConfig(BaseModel):
    """A single proxy entry."""

    url: str = Field(..., description="e.g. http://user:pass@host:port")
    username: str | None = Field(default=None)
    password: str | None = Field(default=None)
    weight: int = Field(default=1, ge=1, description="Relative rotation weight")
    enabled: bool = Field(default=True)


class BrowserProxyConfig(BaseModel):
    """Proxy pool configuration."""

    proxies: list[ProxyConfig] = Field(default_factory=list)
    rotation: Literal["round_robin", "random", "sticky"] = Field(default="round_robin")
    max_failures_before_ban: int = Field(default=5, ge=1)
    health_check_url: str = Field(default="https://example.com")
    health_check_timeout_ms: int = Field(default=10000)


class BrowserConfig(BaseModel):
    """Core browser / navigation settings."""

    # Mode
    headless: bool = Field(default=True, description="Run without a visible window")
    visible: bool = Field(default=False, description="Show a visible browser window")
    executable_path: str | None = Field(default=None)
    channel: str | None = Field(default=None, description="chromium, chrome, msedge, ...")

    # Behaviour
    slow_mo: int = Field(default=0, ge=0, description="Artificial delay between actions (ms)")
    launch_args: list[str] = Field(default_factory=list)

    # Page defaults
    viewport_width: int = Field(default=1280, ge=320)
    viewport_height: int = Field(default=720, ge=300)
    user_agent: str | None = Field(default=None)
    locale: str = Field(default="en-US")
    timezone_id: str | None = Field(default=None)

    # Resource / network control
    block_resource_types: list[str] = Field(
        default_factory=lambda: ["image", "media", "font"]
    )
    navigation_timeout_ms: int = Field(default=30000, ge=1000)
    wait_until: Literal[
        "load", "domcontentloaded", "networkidle", "commit"
    ] = Field(default="domcontentloaded")

    # Robustness
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_base_ms: int = Field(default=1000, ge=100)
    request_delay_min_ms: int = Field(default=500, ge=0)
    request_delay_max_ms: int = Field(default=2000, ge=0)

    # Pooling
    max_pages: int = Field(default=8, ge=1, le=100)
    page_idle_timeout_seconds: int = Field(default=120, ge=5)

    # Captcha
    captcha_detection_enabled: bool = Field(default=True)

    # Fingerprint
    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)

    # Proxy
    proxy: BrowserProxyConfig | None = Field(default=None)

    # Persistence
    storage_dir: str = Field(default="browser_data")
    screenshot_dir: str = Field(default="browser_data/screenshots")
    archive_dir: str = Field(default="browser_data/archives")
    session_dir: str = Field(default="browser_data/sessions")
    cookie_file: str = Field(default="browser_data/cookies.json")


class BrowserAutomationConfig(BaseModel):
    """Root configuration for the browser automation framework."""

    enabled: bool = Field(default=False, description="Master switch")
    browser: BrowserConfig = Field(default_factory=BrowserConfig)

    @property
    def is_enabled(self) -> bool:
        """Whether browser automation is turned on."""
        return self.enabled
