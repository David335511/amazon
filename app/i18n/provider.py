"""LanguageProvider — FastAPI dependency for language detection and switching.

Design decisions:
- Language is determined by (in order): query param → cookie → header → Accept-Language → default.
- The selected language is stored in the request state for access by other components.
- A global `active_translations` dict provides the current TranslationService to sync code.
- Language can be switched via API without page refresh.
- The preference persists in a cookie and can be saved to the user profile.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from typing import Any

from fastapi import Cookie, Depends, Header, Query, Request
from redis.asyncio import Redis

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.i18n.cache import TranslationCache
from app.i18n.loader import TranslationLoader
from app.i18n.service import TranslationService

logger = get_logger(__name__)

# Default language
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ["en", "zh-CN"]

# Context variable for the current language (used in async contexts)
_current_language: ContextVar[str] = ContextVar("current_language", default=DEFAULT_LANGUAGE)
_current_translations: ContextVar[TranslationService | None] = ContextVar(
    "current_translations", default=None,
)


def get_language() -> str:
    """Get the current language from context."""
    return _current_language.get()


def set_language(language: str) -> None:
    """Set the current language in context."""
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    _current_language.set(language)


def get_translations() -> TranslationService | None:
    """Get the current TranslationService from context."""
    return _current_translations.get()


class LanguageProvider:
    """FastAPI dependency that provides the current language and TranslationService.

    Usage:
        @router.get('/endpoint')
        async def endpoint(lang: LanguageProvider = Depends()):
            t = lang.t  # TranslationService
            return {'title': t.t('dashboard.title')}
    """

    def __init__(
        self,
        language: str = DEFAULT_LANGUAGE,
        translations: TranslationService | None = None,
    ) -> None:
        self._language = language
        self._translations = translations or TranslationService(language)

    @property
    def t(self) -> TranslationService:
        """Get the TranslationService for the current language."""
        return self._translations

    @property
    def lang(self) -> str:
        """Get the current language code."""
        return self._language

    @property
    def locale(self) -> LocaleManager:
        """Get the LocaleManager for the current language."""
        return self._translations.locale


async def get_language_provider(
    request: Request,
    accept_language: str | None = Header(default=None),
    lang: str | None = Cookie(default=None),
    redis_client: Redis = Depends(get_redis),
) -> AsyncGenerator[LanguageProvider, Any]:
    """FastAPI dependency that resolves the language from request context.

    Priority: query param > cookie > Accept-Language header > default (en).
    """
    # 1. Query parameter
    query_lang = request.query_params.get("lang")

    # 2. Cookie
    cookie_lang = lang

    # 3. Accept-Language header
    header_lang = None
    if accept_language:
        # Parse first language from Accept-Language
        header_lang = accept_language.split(",")[0].split(";")[0].strip()

    # Determine language
    detected = query_lang or cookie_lang or header_lang or DEFAULT_LANGUAGE
    if detected not in SUPPORTED_LANGUAGES:
        detected = DEFAULT_LANGUAGE

    # Create TranslationService
    loader = TranslationLoader()
    cache = TranslationCache(redis_client)
    translations = TranslationService(
        language=detected,
        loader=loader,
        cache=cache,
    )

    # Set context
    set_language(detected)
    token = _current_translations.set(translations)

    try:
        yield LanguageProvider(language=detected, translations=translations)
    finally:
        _current_translations.reset(token)
