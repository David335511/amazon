"""TranslationService — core service for translating text throughout the platform.

Design decisions:
- Uses TranslationLoader for file I/O and TranslationCache for Redis caching.
- Supports variable interpolation with {placeholder} syntax.
- Supports nested key access with dot notation (e.g., 'common.app.name').
- Falls back to the key itself if translation is missing.
- All system logs, DB fields, and API field names remain in English.
"""

from __future__ import annotations

import re
from typing import Any

from app.i18n.cache import TranslationCache
from app.i18n.loader import TranslationLoader
from app.i18n.locale import LocaleManager
from app.core.logging import get_logger

logger = get_logger(__name__)

# Pattern for variable interpolation: {variable_name}
INTERPOLATION_PATTERN = re.compile(r"\{(\w+)\}")


class TranslationService:
    """Core translation service.

    Usage:
        t = TranslationService('zh-CN')
        t.t('dashboard.title')  # '选品智能仪表盘'
        t.t('common.page', page=1, total=5)  # '第1页，共5页'
        t.lc.format_date(dt)  # Locale-aware date formatting
    """

    def __init__(
        self,
        language: str = "en",
        loader: TranslationLoader | None = None,
        cache: TranslationCache | None = None,
    ) -> None:
        self._language = language
        self._loader = loader or TranslationLoader()
        self._cache = cache
        self._locale = LocaleManager(language)

        # Preload common module (always needed)
        self._common = self._load("common")

    @property
    def locale(self) -> LocaleManager:
        """Get the locale manager for this language."""
        return self._locale

    @property
    def language(self) -> str:
        return self._language

    def switch_language(self, language: str) -> None:
        """Switch to a different language."""
        self._language = language
        self._locale = LocaleManager(language)
        self._common = self._load("common")

    # ── Translation ─────────────────────────────────────────

    def t(
        self,
        key: str,
        *,
        default: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Translate a key with optional variable interpolation.

        Args:
            key: Dot-notation key (e.g., 'dashboard.title', 'common.page').
            default: Fallback text if key is not found.
            **kwargs: Variables for interpolation (e.g., page=1, total=5).

        Returns:
            Translated string.
        """
        # Parse key: module.subkey[.subkey...]
        parts = key.split(".")
        if len(parts) < 2:
            logger.warning("Invalid translation key format: %s", key)
            return default or key

        module_name = parts[0]
        translation_key = ".".join(parts[1:])

        # Load module translations
        translations = self._load(module_name)

        # Navigate nested keys
        value = self._get_nested(translations, translation_key)

        if value is None:
            # Try common module as fallback
            common_value = self._get_nested(self._common, key)
            if common_value is not None:
                value = common_value
            else:
                logger.debug("Missing translation: %s (%s)", key, self._language)
                return default or key

        # Interpolate variables
        if kwargs:
            value = self._interpolate(str(value), **kwargs)

        return str(value)

    def _load(self, module: str) -> dict[str, Any]:
        """Load translations for a module, checking cache first."""
        # Try cache
        if self._cache is not None:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Can't await in sync context, skip cache
                    pass
                else:
                    cached = loop.run_until_complete(
                        self._cache.get(self._language, module),
                    )
                    if cached is not None:
                        return cached
            except (RuntimeError, Exception):
                pass

        # Load from disk
        return self._loader.load(self._language, module)

    @staticmethod
    def _get_nested(data: dict[str, Any], key: str) -> Any:
        """Get a nested value from a dict using dot notation."""
        current = data
        for part in key.split("."):
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return None
            else:
                return None
        return current

    @staticmethod
    def _interpolate(text: str, **kwargs: Any) -> str:
        """Replace {variable} placeholders with values."""
        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            val = kwargs.get(var_name)
            if val is None:
                return match.group(0)  # Keep placeholder if no value
            return str(val)
        return INTERPOLATION_PATTERN.sub(replace, text)

    # ── Bulk Translation ────────────────────────────────────

    def translate_dict(
        self,
        data: dict[str, Any],
        key_prefix: str = "",
    ) -> dict[str, Any]:
        """Translate all string values in a dict recursively.

        Used for translating API responses before sending to the frontend.
        Only translates values that match known translation keys.
        """
        result: dict[str, Any] = {}
        for k, v in data.items():
            full_key = f"{key_prefix}.{k}" if key_prefix else k
            if isinstance(v, str) and v.startswith("t:"):
                # Value is a translation reference: t:dashboard.title
                result[k] = self.t(v[2:])
            elif isinstance(v, dict):
                result[k] = self.translate_dict(v, key_prefix=full_key)
            elif isinstance(v, list):
                result[k] = [
                    self.translate_dict(item, key_prefix=full_key)
                    if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result

    # ── Module Access ────────────────────────────────────────

    def get_module(self, module: str) -> dict[str, Any]:
        """Get all translations for a module."""
        return self._load(module)

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Get all translations for the current language."""
        return self._loader.load_all(self._language)
