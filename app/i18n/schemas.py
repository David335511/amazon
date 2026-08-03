"""Pydantic schemas for the internationalization API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class LanguageInfo(BaseModel):
    """A single supported language."""

    model_config = ConfigDict(extra="ignore")

    code: str
    display_name: str
    native_name: str
    is_default: bool = False


class LanguageListRead(BaseModel):
    languages: list[LanguageInfo]
    total: int


class CurrentLanguageRead(BaseModel):
    language: str
    display_name: str
    native_name: str
    source: str


class LocaleFormattingRead(BaseModel):
    """Exemplar formatting for a language (date / number / currency / timezone)."""

    language: str
    date_short: str
    date_long: str
    date_time: str
    number: str
    percentage: str
    currency: str
    currency_code: str
    timezone: str
    plural_singular: str
    plural_other: str
    first_day_of_week: int


class SwitchResult(BaseModel):
    status: str
    language: str
    display_name: str
    native_name: str
    persisted: dict[str, bool] = {}


class PreferenceRead(BaseModel):
    user_id: str | None = None
    device_id: str | None = None
    language: str | None = None
    source: str | None = None


class TranslationModuleRead(BaseModel):
    language: str
    module: str
    translations: dict[str, Any] = {}
    key_count: int = 0


class TranslationBundleRead(BaseModel):
    language: str
    modules: dict[str, dict[str, Any]] = {}
    total_keys: int = 0
    cached: bool = False


class ValidationFindings(BaseModel):
    language: str | None = None
    module: str
    key: str


class ValidationRead(BaseModel):
    is_valid: bool
    total_keys: int
    errors: int
    warnings: int
    missing_keys: list[ValidationFindings] = []
    unused_keys: list[ValidationFindings] = []
    duplicate_keys: list[ValidationFindings] = []
    module_mismatches: list[dict[str, str]] = []
    code_usage: dict[str, Any] = {}
    summary: str


class I18nCapabilities(BaseModel):
    enabled: bool
    default_language: str
    fallback_language: str
    supported_languages: list[str]
    modules: list[str]
    plural_rules: list[str]
    currency_codes: list[str]
    cache_ttl: int


class I18nStats(BaseModel):
    available_languages: int
    total_modules: int
    total_keys: int
    cached_languages: int
    persisted_preferences: int
    last_validation_valid: bool | None = None


class ReloadResult(BaseModel):
    reloaded: bool
    languages: int
    modules: int
