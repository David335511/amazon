"""Internationalization API routes — language switching and translation management.

Endpoints:
- GET    /i18n/languages — List available languages
- GET    /i18n/current — Get current language
- POST   /i18n/switch — Switch language
- GET    /i18n/translations/{module} — Get translations for a module
- GET    /i18n/validate — Validate translation completeness
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, Query, Response
from redis.asyncio import Redis

from app.core.logging import get_logger
from app.core.redis import get_redis
from app.i18n.cache import TranslationCache
from app.i18n.loader import TranslationLoader
from app.i18n.provider import (
    SUPPORTED_LANGUAGES,
    LanguageProvider,
    get_language_provider,
)
from app.i18n.service import TranslationService
from app.i18n.validator import TranslationValidator

logger = get_logger(__name__)

router = APIRouter(prefix="/i18n", tags=["i18n"])


@router.get(
    "/languages",
    summary="List available languages",
    description="Returns all available languages with display names.",
)
async def list_languages() -> dict[str, Any]:
    """List all available languages."""
    loader = TranslationLoader()
    languages = loader.list_languages()
    from app.i18n.locale import BUILTIN_LOCALES
    result = []
    for lang in languages:
        config = BUILTIN_LOCALES.get(lang)
        result.append({
            "code": lang,
            "display_name": config.display_name if config else lang,
            "native_name": config.native_name if config else lang,
            "is_current": False,
        })
    return {"languages": result, "total": len(result)}


@router.get(
    "/current",
    summary="Get current language",
    description="Returns the currently active language.",
)
async def get_current_language(
    lang_provider: LanguageProvider = Depends(get_language_provider),
) -> dict[str, Any]:
    """Get the current language."""
    from app.i18n.locale import BUILTIN_LOCALES
    config = BUILTIN_LOCALES.get(lang_provider.lang)
    return {
        "language": lang_provider.lang,
        "display_name": config.display_name if config else lang_provider.lang,
        "native_name": config.native_name if config else lang_provider.lang,
    }


@router.post(
    "/switch",
    summary="Switch language",
    description="Switch the active language. Sets a cookie and returns translations.",
    response_model=None,
)
async def switch_language(
    language: str = Query(..., description="Language code (e.g., 'en', 'zh-CN')"),
    response: Response = None,
) -> dict[str, Any]:
    """Switch the active language."""
    if language not in SUPPORTED_LANGUAGES:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported language '{language}'. Supported: {SUPPORTED_LANGUAGES}",
        )

    # Set cookie so subsequent requests detect the language
    if response is not None:
        response.set_cookie(
            key="lang",
            value=language,
            max_age=31536000,
            httponly=True,
            samesite="lax",
        )

    # Preload translations for the new language
    loader = TranslationLoader()
    modules = loader.list_modules(language)
    for module in modules:
        loader.load(language, module)

    from app.i18n.locale import BUILTIN_LOCALES
    config = BUILTIN_LOCALES.get(language)

    return {
        "status": "switched",
        "language": language,
        "display_name": config.display_name if config else language,
        "native_name": config.native_name if config else language,
    }


@router.get(
    "/translations/{module:path}",
    summary="Get translations for a module",
    description="Returns all translation keys for a specific module in the current language.",
)
async def get_translations(
    module: str,
    lang_provider: LanguageProvider = Depends(get_language_provider),
) -> dict[str, Any]:
    """Get translations for a module."""
    data = lang_provider.t.get_module(module)
    return {
        "language": lang_provider.lang,
        "module": module,
        "translations": data,
        "key_count": len(data) if data else 0,
    }


@router.get(
    "/all",
    summary="Get all translations",
    description="Returns all translations for the current language.",
)
async def get_all_translations(
    lang_provider: LanguageProvider = Depends(get_language_provider),
) -> dict[str, Any]:
    """Get all translations for the current language."""
    data = lang_provider.t.get_all()
    total_keys = sum(len(v) for v in data.values())
    return {
        "language": lang_provider.lang,
        "modules": data,
        "total_keys": total_keys,
    }


@router.get(
    "/validate",
    summary="Validate translations",
    description="Validates that all translation keys exist in all languages.",
)
async def validate_translations() -> dict[str, Any]:
    """Validate translation completeness."""
    validator = TranslationValidator()
    result = validator.validate()
    return {
        "is_valid": result.is_valid,
        "total_keys": result.total_keys,
        "errors": result.errors,
        "warnings": result.warnings,
        "missing_keys": result.missing_keys[:20],
        "module_mismatches": result.module_mismatches,
        "summary": result.summary(),
    }
