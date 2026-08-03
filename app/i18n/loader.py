"""TranslationLoader — loads translation JSON files from disk.

Design decisions:
- Scans the translations directory for language folders.
- Each language folder contains one JSON file per module.
- Files are loaded lazily — only when first accessed.
- Supports both JSON and YAML formats (YAML via PyYAML if installed).
- Thread-safe loading with a simple lock.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "translations"


class TranslationLoader:
    """Loads translation files from disk.

    Usage:
        loader = TranslationLoader()
        languages = loader.list_languages()  # ['en', 'zh-CN']
        modules = loader.list_modules('en')  # ['common', 'dashboard', ...]
        data = loader.load('en', 'dashboard')  # dict of keys
    """

    def __init__(self, translations_dir: str | Path | None = None) -> None:
        self._dir = Path(translations_dir) if translations_dir else TRANSLATIONS_DIR
        self._cache: dict[str, dict[str, dict[str, Any]]] = {}  # lang -> module -> data
        self._lock = Lock()

    # ── Language Discovery ──────────────────────────────────

    def list_languages(self) -> list[str]:
        """List all available language codes."""
        if not self._dir.exists():
            logger.warning("Translations directory not found: %s", self._dir)
            return []
        return sorted([
            d.name for d in self._dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ])

    def list_modules(self, language: str) -> list[str]:
        """List all available modules for a language."""
        lang_dir = self._dir / language
        if not lang_dir.exists():
            return []
        return sorted([
            f.stem for f in lang_dir.iterdir()
            if f.suffix in (".json", ".yaml", ".yml")
        ])

    def language_exists(self, language: str) -> bool:
        """Check if a language is available."""
        return (self._dir / language).is_dir()

    # ── Loading ─────────────────────────────────────────────

    def load(self, language: str, module: str) -> dict[str, Any]:
        """Load translations for a specific language and module.

        Results are cached in memory for the lifetime of the loader.

        Args:
            language: Language code (e.g., 'en', 'zh-CN').
            module: Module name (e.g., 'common', 'dashboard').

        Returns:
            Dict of translation keys to values.
        """
        with self._lock:
            # Check cache
            if language in self._cache and module in self._cache[language]:
                return self._cache[language][module]

            # Load from file
            data = self._load_file(language, module)

            # Cache
            if language not in self._cache:
                self._cache[language] = {}
            self._cache[language][module] = data

            return data

    def load_all(self, language: str) -> dict[str, dict[str, Any]]:
        """Load all modules for a language.

        Returns:
            Dict of module_name -> translation_key_value dict.
        """
        result: dict[str, dict[str, Any]] = {}
        for module in self.list_modules(language):
            result[module] = self.load(language, module)
        return result

    def _load_file(self, language: str, module: str) -> dict[str, Any]:
        """Load a single translation file from disk."""
        # Try JSON first
        json_path = self._dir / language / f"{module}.json"
        if json_path.exists():
            try:
                with open(json_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.error("Failed to load %s: %s", json_path, exc)
                return {}

        # Try YAML
        yaml_path = self._dir / language / f"{module}.yaml"
        if yaml_path.exists():
            try:
                import yaml
                with open(yaml_path, encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except ImportError:
                logger.warning("PyYAML not installed, cannot load %s", yaml_path)
                return {}
            except Exception as exc:
                logger.error("Failed to load %s: %s", yaml_path, exc)
                return {}

        logger.warning("Translation file not found: %s/%s", language, module)
        return {}

    # ── Cache Management ────────────────────────────────────

    def clear_cache(self, language: str | None = None) -> None:
        """Clear the in-memory cache."""
        with self._lock:
            if language:
                self._cache.pop(language, None)
            else:
                self._cache.clear()

    def preload(self, language: str) -> int:
        """Preload all modules for a language into cache.

        Returns:
            Number of modules loaded.
        """
        count = 0
        for module in self.list_modules(language):
            self.load(language, module)
            count += 1
        logger.info("Preloaded %d modules for language '%s'", count, language)
        return count
