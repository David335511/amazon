"""Internationalization API — language resolution, switching, translation and validation.

Endpoints:
- GET   /i18n/capabilities       — supported languages, modules, formats
- GET   /i18n/languages          — list available languages
- GET   /i18n/current            — resolve the current language for this request
- POST  /i18n/switch             — switch language (persists to cookie + DB + profile)
- GET   /i18n/preference         — stored language preference for a user/device
- GET   /i18n/bundle             — full translation bundle for a language (lazy load)
- GET   /i18n/translations/{module} — a single module's translations
- GET   /i18n/locale/{language}  — exemplar locale formatting (date/number/currency/tz/plural)
- POST  /i18n/validate           — report missing / unused / duplicate keys
- POST  /i18n/reload             — drop caches and reload translation files
- GET   /i18n/stats              — platform aggregates
"""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from app.core.dependencies import get_i18n_manager
from app.i18n import I18nManager
from app.i18n.errors import LanguageUnsupportedError
from app.i18n.schemas import (
    CurrentLanguageRead,
    I18nCapabilities,
    I18nStats,
    LanguageListRead,
    LocaleFormattingRead,
    PreferenceRead,
    ReloadResult,
    SwitchResult,
    TranslationBundleRead,
    TranslationModuleRead,
    ValidationRead,
)

router = APIRouter(prefix="/i18n", tags=["i18n"])

ManagerDep = Annotated[I18nManager, Depends(get_i18n_manager)]


def _device_id(request: Request) -> str | None:
    return request.headers.get("X-Device-Id")


@router.get("/capabilities", response_model=I18nCapabilities)
async def capabilities(manager: ManagerDep) -> I18nCapabilities:
    """Supported languages, modules, plural rules and currency codes."""
    return manager.capabilities()


@router.get("/languages", response_model=LanguageListRead)
async def list_languages(manager: ManagerDep) -> LanguageListRead:
    """List all supported languages with display/native names."""
    return manager.list_languages()


@router.get("/current", response_model=CurrentLanguageRead)
async def current_language(
    manager: ManagerDep,
    request: Request,
    lang_cookie: str | None = Cookie(default=None, alias="lang"),
    accept_language: str | None = Header(default=None),
) -> CurrentLanguageRead:
    """Resolve the current language for this request.

    Priority: query param > cookie > Accept-Language header > stored preference
    (for a user/device) > default.
    """
    query = request.query_params.get("lang")
    resolved = await manager.resolve(
        query=query,
        cookie=lang_cookie,
        header=_parse_accept_language(accept_language),
        user_id=request.query_params.get("user_id"),
        device_id=_device_id(request),
    )
    return manager.current(resolved)


@router.post("/switch", response_model=SwitchResult)
async def switch_language(
    manager: ManagerDep,
    request: Request,
    response: Response,
    language: str = Query(..., description="Language code (e.g. 'en', 'zh-CN')"),
    user_id: str | None = Query(default=None),
) -> SwitchResult:
    """Switch the active language and persist it everywhere.

    Sets a browser cookie, upserts the database preference (per user/device) and
    writes the user's settings profile — so the choice survives across requests,
    devices and sessions without any page refresh.
    """
    try:
        return await manager.switch(
            language,
            response=response,
            user_id=user_id,
            device_id=_device_id(request),
            source="manual" if user_id else "cookie",
        )
    except LanguageUnsupportedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/preference", response_model=PreferenceRead)
async def get_preference(
    manager: ManagerDep,
    request: Request,
    user_id: str | None = Query(default=None),
) -> PreferenceRead:
    """Return the stored language preference for a user/device (or null)."""
    pref = await manager.get_preference(
        user_id=user_id, device_id=_device_id(request),
    )
    if pref is None:
        return PreferenceRead()
    return PreferenceRead(**pref)


@router.get("/bundle", response_model=TranslationBundleRead)
async def get_bundle(
    manager: ManagerDep,
    request: Request,
    language: str | None = Query(default=None),
    use_cache: bool = Query(default=True),
) -> TranslationBundleRead:
    """Return the full translation bundle for a language (lazy-loaded)."""
    query = language or request.query_params.get("lang")
    resolved_lang = manager.switcher.normalize(query)
    return await manager.get_bundle(resolved_lang, use_cache=use_cache)


@router.get("/translations/{module:path}", response_model=TranslationModuleRead)
async def get_module(
    manager: ManagerDep,
    module: str,
    language: str | None = Query(default=None),
) -> TranslationModuleRead:
    """Return a single module's translations for the given language."""
    return manager.get_module(manager.switcher.normalize(language), module)


@router.get("/locale/{language}", response_model=LocaleFormattingRead)
async def locale_formatting(
    manager: ManagerDep, language: str
) -> LocaleFormattingRead:
    """Exemplar locale formatting for a language (dates/numbers/currency/tz/plural)."""
    return manager.format(language)


@router.post("/validate", response_model=ValidationRead)
async def validate_translations(
    manager: ManagerDep,
    include_code_usage: bool = Query(default=False),
) -> ValidationRead:
    """Validate translation completeness: missing / unused / duplicate keys."""
    return manager.validate(include_code_usage=include_code_usage)


@router.post("/reload", response_model=ReloadResult)
async def reload_translations(manager: ManagerDep) -> ReloadResult:
    """Drop caches and reload translation files from disk."""
    return await manager.reload()


@router.get("/stats", response_model=I18nStats)
async def stats(manager: ManagerDep) -> I18nStats:
    """Platform-wide i18n aggregates."""
    return await manager.stats()


def _parse_accept_language(header: str | None) -> str | None:
    """Return the primary language from an Accept-Language header, if any."""
    if not header:
        return None
    return header.split(",")[0].split(";")[0].strip()
