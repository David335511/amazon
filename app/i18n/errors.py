"""Exceptions for the internationalization system."""

from __future__ import annotations


class I18nError(Exception):
    """Base error for the i18n subsystem."""


class LanguageUnsupportedError(I18nError):
    """A language code is not in the supported whitelist."""


class TranslationNotFoundError(I18nError):
    """A translation key or module could not be resolved."""


class TranslationValidationError(I18nError):
    """Translation files failed structural validation (missing/duplicate keys)."""


class LocaleFormatError(I18nError):
    """A locale value could not be formatted."""
