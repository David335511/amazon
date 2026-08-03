"""Multilingual AI support — errors."""

from __future__ import annotations


class MultilingualError(Exception):
    """Base error for the multilingual subsystem."""


class UnsupportedLanguageError(MultilingualError):
    """The requested output language is not supported."""


class LanguageDetectionError(MultilingualError):
    """Language could not be detected from the input."""
