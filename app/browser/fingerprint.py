"""Browser fingerprint randomization.

Generates plausible user-agent / viewport / locale / timezone / DPR combos so
every context looks like a fresh, distinct visitor. Applied at context-creation
time by the `BrowserManager`.

NOTE: Full stealth (WebRTC masking, canvas noise, navigator spoofing) is a
separate concern that requires a stealth patch. This module randomizes the
surface-level, low-risk attributes that need no patching.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.browser.config import FingerprintConfig

# A small curated pool of realistic desktop Chrome user agents. In production
# this would be pulled from an external UA database; the pool keeps the module
# dependency-free and deterministic.
_CHROME_VERSIONS = [
    "131.0.6778.86",
    "131.0.6778.204",
    "132.0.6834.46",
    "132.0.6834.83",
    "133.0.6943.53",
    "134.0.6998.35",
]

_OS_TOKENS = [
    "Windows NT 10.0; Win64; x64",
    "Windows NT 10.0; WOW64",
    "Macintosh; Intel Mac OS X 10_15_7",
    "Macintosh; Intel Mac OS X 14_4_1",
    "X11; Linux x86_64",
]


@dataclass
class Fingerprint:
    """A generated, internally-consistent browser fingerprint."""

    user_agent: str
    viewport: tuple[int, int]
    device_scale_factor: int
    locale: str
    timezone_id: str
    extra: dict = field(default_factory=dict)


def _random_user_agent() -> str:
    version = random.choice(_CHROME_VERSIONS)
    os_token = random.choice(_OS_TOKENS)
    if "Linux" in os_token:
        platform = "Linux; x86_64"
    elif "Macintosh" in os_token:
        platform = "Macintosh; " + os_token
    else:
        platform = os_token
    return (
        f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version} Safari/537.36"
    )


class FingerprintRandomizer:
    """Generates randomized browser fingerprints from config."""

    def __init__(self, config: FingerprintConfig | None = None) -> None:
        self._config = config or FingerprintConfig()

    def generate(self, base_fp: Fingerprint | None = None) -> Fingerprint:
        """Generate a fingerprint, keeping stable base attributes."""
        cfg = self._config
        base = base_fp

        user_agent = (
            _random_user_agent()
            if cfg.randomize_user_agent
            else (base.user_agent if base else "")
        )

        if cfg.randomize_viewport:
            width = random.randint(cfg.viewport_width_min, cfg.viewport_width_max)
            height = random.randint(cfg.viewport_height_min, cfg.viewport_height_max)
        else:
            width = base.viewport[0] if base else 1280
            height = base.viewport[1] if base else 720
        viewport = (width, height)

        dsf = (
            random.choice([1, 1, 1, 2])
            if cfg.randomize_device_scale_factor
            else (base.device_scale_factor if base else 1)
        )

        locale = (
            random.choice(cfg.locales)
            if cfg.randomize_locale and cfg.locales
            else (base.locale if base else "en-US")
        )

        timezone = (
            random.choice(cfg.timezones)
            if cfg.randomize_timezone and cfg.timezones
            else (base.timezone_id if base else None)
        )

        return Fingerprint(
            user_agent=user_agent or "Mozilla/5.0 (compatible; AmazonSourcer)",
            viewport=viewport,
            device_scale_factor=dsf,
            locale=locale,
            timezone_id=timezone,
            extra={},
        )
