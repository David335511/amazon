"""Internationalization facade.

`I18nManager` is the ONLY entry point for resolving languages, translating text,
formatting locale values (dates, numbers, currency, timezones), switching
languages (with browser + database + user-profile persistence) and validating
translation completeness.

Design decisions:
- **Lazy loading** — only the current language's modules are loaded on demand;
  nothing is read at import time.
- **JSON or YAML** — the loader reads ``.json`` / ``.yaml`` / ``.yml`` files.
- **Validator** — reports missing, unused and duplicate keys plus module
  mismatches, and can scan the codebase for translation-key usage.
- **New languages** are added by dropping a directory under ``translations/``
  (and listing it in the config whitelist) — no application code changes.
- **Only displayed content is translated**; logs, DB fields and API fields stay
  in English.
"""

from __future__ import annotations

from typing import Any

from app.i18n.cache import TranslationCache
from app.i18n.config import I18nConfig
from app.i18n.errors import LanguageUnsupportedError
from app.i18n.loader import TranslationLoader
from app.i18n.locale import BUILTIN_LOCALES, PLURAL_RULES, LocaleManager
from app.i18n.repository import I18nRepository
from app.i18n.schemas import (
    CurrentLanguageRead,
    I18nCapabilities,
    I18nStats,
    LanguageInfo,
    LanguageListRead,
    LocaleFormattingRead,
    ReloadResult,
    SwitchResult,
    TranslationBundleRead,
    TranslationModuleRead,
    ValidationFindings,
    ValidationRead,
)
from app.i18n.service import TranslationService
from app.i18n.switcher import LanguageSwitcher, ResolvedLanguage
from app.i18n.validator import TranslationValidator


class I18nManager:
    """Facade for the internationalization system."""

    def __init__(
        self,
        repository: I18nRepository | None = None,
        config: I18nConfig | None = None,
        loader: TranslationLoader | None = None,
        cache: TranslationCache | None = None,
        session=None,
    ) -> None:
        self._config = config or I18nConfig()
        self._loader = loader or TranslationLoader(self._config.translations_dir)
        self._cache = cache or TranslationCache(default_ttl=self._config.cache_ttl)
        self._repo = repository or I18nRepository.__new__(I18nRepository)
        self._switcher = LanguageSwitcher(self._repo, config=self._config, session=session)
        self._validator = TranslationValidator(self._config.translations_dir)

    # ── Capabilities ──────────────────────────────────────────────────────

    def capabilities(self) -> I18nCapabilities:
        modules = sorted(self._loader.list_modules(self._config.default_language))
        return I18nCapabilities(
            enabled=self._config.enabled,
            default_language=self._config.default_language,
            fallback_language=self._config.fallback_language,
            supported_languages=list(self._config.supported_languages),
            modules=modules,
            plural_rules=sorted(PLURAL_RULES.keys()),
            currency_codes=sorted({c.currency_code for c in BUILTIN_LOCALES.values()}),
            cache_ttl=self._config.cache_ttl,
        )

    def list_languages(self) -> LanguageListRead:
        langs: list[LanguageInfo] = []
        for code in self._config.supported_languages:
            config = BUILTIN_LOCALES.get(code)
            langs.append(LanguageInfo(
                code=code,
                display_name=config.display_name if config else code,
                native_name=config.native_name if config else code,
                is_default=code == self._config.default_language,
            ))
        return LanguageListRead(languages=langs, total=len(langs))

    # ── Resolution & current language ─────────────────────────────────────

    async def resolve(
        self,
        *,
        query: str | None = None,
        cookie: str | None = None,
        header: str | None = None,
        user_id=None,
        device_id: str | None = None,
    ) -> ResolvedLanguage:
        return await self._switcher.resolve(
            query=query, cookie=cookie, header=header,
            user_id=user_id, device_id=device_id,
        )

    def current(self, resolved: ResolvedLanguage) -> CurrentLanguageRead:
        config = BUILTIN_LOCALES.get(resolved.language)
        return CurrentLanguageRead(
            language=resolved.language,
            display_name=config.display_name if config else resolved.language,
            native_name=config.native_name if config else resolved.language,
            source=resolved.source,
        )

    # ── Translation ───────────────────────────────────────────────────────

    def translate(self, language: str, key: str, **kwargs: Any) -> str:
        """Translate a dot-notation key for a language with interpolation."""
        service = TranslationService(language, loader=self._loader)
        return service.t(key, **kwargs)

    def get_module(self, language: str, module: str) -> TranslationModuleRead:
        service = TranslationService(language, loader=self._loader)
        data = service.get_module(module)
        return TranslationModuleRead(
            language=language, module=module,
            translations=data, key_count=_count_keys(data),
        )

    async def get_bundle(self, language: str, *, use_cache: bool = True) -> TranslationBundleRead:
        """Return the full bundle for a language (lazy-loads the current language)."""
        if not self._config.enabled:
            language = self._config.default_language
        if not self._switcher.is_supported(language):
            language = self._config.default_language

        cached = False
        modules: dict[str, dict[str, Any]] = {}
        if use_cache:
            cached = await self._cache.get(language, "*bundle")
            if cached:
                return TranslationBundleRead(
                    language=language, modules=cached,
                    total_keys=sum(_count_keys(v) for v in cached.values()), cached=True,
                )

        modules = self._loader.load_all(language)
        if use_cache:
            await self._cache.set(language, "*bundle", modules)
        return TranslationBundleRead(
            language=language, modules=modules,
            total_keys=sum(_count_keys(v) for v in modules.values()), cached=False,
        )

    def format(self, language: str) -> LocaleFormattingRead:
        """Exemplar locale formatting for a language (date/number/currency/tz/plural)."""
        if not self._switcher.is_supported(language):
            language = self._config.default_language
        lm = LocaleManager(language)
        cfg = lm.config
        import datetime as _dt
        from datetime import UTC

        now = _dt.datetime.now(UTC)
        return LocaleFormattingRead(
            language=language,
            date_short=lm.format_date(now),
            date_long=lm.format_date(now, fmt=cfg.date_long),
            date_time=lm.format_datetime(now),
            number=lm.format_number(1234567.89),
            percentage=lm.format_percentage(0.234),
            currency=lm.format_currency(1234.56),
            currency_code=cfg.currency_code,
            timezone=cfg.default_timezone,
            plural_singular=lm.pluralize(1, "item"),
            plural_other=lm.pluralize(5, "item"),
            first_day_of_week=cfg.first_day_of_week,
        )

    # ── Switching & persistence ───────────────────────────────────────────

    async def switch(
        self,
        language: str,
        *,
        response=None,
        user_id=None,
        device_id: str | None = None,
        source: str = "manual",
    ) -> SwitchResult:
        if not self._switcher.is_supported(language):
            raise LanguageUnsupportedError(
                f"Unsupported language '{language}'. Supported: {self._switcher.supported()}"
            )
        persisted = await self._switcher.switch(
            language, response=response,
            user_id=user_id, device_id=device_id, source=source,
        )
        config = BUILTIN_LOCALES.get(language)
        return SwitchResult(
            status="switched",
            language=language,
            display_name=config.display_name if config else language,
            native_name=config.native_name if config else language,
            persisted=persisted,
        )

    async def get_preference(self, *, user_id=None, device_id: str | None = None):
        return await self._switcher.get_preference(user_id=user_id, device_id=device_id)

    # ── Validation ────────────────────────────────────────────────────────

    def validate(self, *, include_code_usage: bool = False) -> ValidationRead:
        result = self._validator.validate()
        code_usage: dict[str, Any] = {}
        if include_code_usage:
            code_usage = self._validator.scan_code_usage()
        return ValidationRead(
            is_valid=result.is_valid,
            total_keys=result.total_keys,
            errors=result.errors,
            warnings=result.warnings,
            missing_keys=[_finding(f) for f in result.missing_keys],
            unused_keys=[_finding(f) for f in result.unused_keys],
            duplicate_keys=[_finding(f) for f in result.duplicate_keys],
            module_mismatches=result.module_mismatches,
            code_usage=code_usage,
            summary=result.summary(),
        )

    async def reload(self) -> ReloadResult:
        """Drop caches and reload translation files from disk."""
        await self._cache.invalidate()
        self._loader.clear_cache()
        languages = self._loader.list_languages()
        modules = 0
        for lang in languages:
            modules += len(self._loader.list_modules(lang))
        return ReloadResult(reloaded=True, languages=len(languages), modules=modules)

    # ── Stats ─────────────────────────────────────────────────────────────

    async def stats(self) -> I18nStats:
        langs = self._loader.list_languages()
        modules = set()
        total_keys = 0
        for lang in langs:
            for module in self._loader.list_modules(lang):
                modules.add(module)
                total_keys += _count_keys(self._loader.load(lang, module))
        prefs = 0
        try:
            prefs = await self._repo.count()
        except Exception:  # pragma: no cover - repo may be stub
            prefs = 0
        return I18nStats(
            available_languages=len(langs),
            total_modules=len(modules),
            total_keys=total_keys,
            cached_languages=len(getattr(self._loader, "_cache", {})),
            persisted_preferences=prefs,
        )

    # ── Direct access to underlying components ────────────────────────────

    @property
    def switcher(self) -> LanguageSwitcher:
        return self._switcher

    @property
    def loader(self) -> TranslationLoader:
        return self._loader

    @property
    def validator(self) -> TranslationValidator:
        return self._validator

    @property
    def config(self) -> I18nConfig:
        return self._config


def _count_keys(data: dict[str, Any]) -> int:
    return sum(_count_keys(v) if isinstance(v, dict) else 1 for v in data.values())


def _finding(f: dict[str, str]) -> ValidationFindings:
    return ValidationFindings(
        language=f.get("language"),
        module=f.get("module", ""),
        key=f.get("key", ""),
    )
