"""Internationalization system for the Amazon AI Commerce Platform.

Design decisions:
- Translations are stored as JSON/YAML files, one per module per language, under
  ``translations/<lang>/``.
- Every translation key must exist in every language (enforced by the validator,
  which reports missing, unused and duplicate keys).
- Lazy loading: only the current language is loaded into memory.
- Redis cache for production, in-memory dict for development.
- Selected language persists to the browser cookie, the database
  (``i18n_language_preferences``) and the user profile.
- Language resolution priority: query param > cookie > Accept-Language header >
  stored preference > default.
- System logs, DB fields, and API field names remain in English.
- Only displayed content is translated.
- New languages are added by dropping a directory under ``translations/`` — no
  application code changes.
"""

from app.i18n.cache import TranslationCache
from app.i18n.config import I18nConfig
from app.i18n.loader import TranslationLoader
from app.i18n.locale import LocaleConfig, LocaleManager
from app.i18n.manager import I18nManager
from app.i18n.models import LanguagePreference, LanguageSource
from app.i18n.provider import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    LanguageProvider,
    get_language,
    get_translations,
    set_language,
)
from app.i18n.repository import I18nRepository
from app.i18n.service import TranslationService
from app.i18n.switcher import LanguageSwitcher
from app.i18n.validator import TranslationValidator

__all__ = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "I18nConfig",
    "I18nManager",
    "I18nRepository",
    "LanguagePreference",
    "LanguageProvider",
    "LanguageSource",
    "LanguageSwitcher",
    "LocaleConfig",
    "LocaleManager",
    "TranslationCache",
    "TranslationLoader",
    "TranslationService",
    "TranslationValidator",
    "get_language",
    "get_translations",
    "set_language",
]
