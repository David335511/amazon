"""Internationalization system for the Amazon AI Commerce Platform.

Design decisions:
- Translations are stored as JSON files, one per module per language.
- Every translation key must exist in every language (enforced by validator).
- Lazy loading: only the current language is loaded into memory.
- Redis cache for production, in-memory dict for development.
- System logs, DB fields, and API field names remain in English.
- Only displayed content is translated.
- New languages can be added by creating a new directory — no code changes needed.
"""

from app.i18n.loader import TranslationLoader
from app.i18n.cache import TranslationCache
from app.i18n.service import TranslationService
from app.i18n.locale import LocaleManager, LocaleConfig
from app.i18n.provider import LanguageProvider, get_language, set_language
from app.i18n.validator import TranslationValidator

__all__ = [
    "TranslationLoader",
    "TranslationCache",
    "TranslationService",
    "LocaleManager",
    "LocaleConfig",
    "LanguageProvider",
    "get_language",
    "set_language",
    "TranslationValidator",
]
