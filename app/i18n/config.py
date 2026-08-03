"""Internationalization (i18n) configuration.

Controls the default/fallback language, the set of supported languages, how the
selected language persists (browser cookie, database, user profile), and the
translation cache TTL.
"""

from __future__ import annotations

from pydantic import BaseModel


class I18nConfig(BaseModel):
    """Configuration for the internationalization system.

    - ``default_language`` is used when no request signal selects a language.
    - ``supported_languages`` is the whitelist the switcher / provider accept.
    - ``fallback_language`` is used for any key missing from the current language.
    - Persistence flags control whether switching writes to the database and the
      user's profile in addition to the browser cookie.
    """

    enabled: bool = True
    default_language: str = "en"
    fallback_language: str = "en"
    supported_languages: list[str] = ["en", "zh-CN"]
    # Browser persistence.
    cookie_name: str = "lang"
    cookie_max_age: int = 31536000  # 1 year
    cookie_httponly: bool = True
    cookie_samesite: str = "lax"
    # Database / user-profile persistence.
    persist_to_db: bool = True
    persist_to_user_profile: bool = True
    device_id_header: str = "X-Device-Id"
    # Translation cache TTL (seconds).
    cache_ttl: int = 3600
    # Override the translations directory (defaults to <project>/translations).
    translations_dir: str | None = None

    @property
    def as_snapshot(self) -> dict:
        return self.model_dump()
