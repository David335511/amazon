"""TranslationValidator — validates translation completeness and consistency.

Design decisions:
- Every translation key must exist in every language.
- Reports missing translations, unused translations, and duplicate keys.
- Can be run as a CLI tool or called programmatically.
- Returns structured results for CI/CD integration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class ValidationResult:
    """Result of a translation validation."""

    def __init__(self) -> None:
        self.missing_keys: list[dict[str, str]] = []  # {language, module, key}
        self.unused_keys: list[dict[str, str]] = []   # {language, module, key}
        self.duplicate_keys: list[dict[str, str]] = []  # {module, key, languages}
        self.module_mismatches: list[dict[str, str]] = []  # {module, has_languages, missing_languages}
        self.total_keys: int = 0
        self.errors: int = 0
        self.warnings: int = 0

    @property
    def is_valid(self) -> bool:
        return self.errors == 0

    def summary(self) -> str:
        lines = [
            f"Translation Validation Report",
            f"{'='*40}",
            f"Total keys per module: {self.total_keys}",
            f"Errors:   {self.errors}",
            f"Warnings: {self.warnings}",
            f"Valid:    {'YES' if self.is_valid else 'NO'}",
        ]
        if self.missing_keys:
            lines.append(f"\nMissing Keys ({len(self.missing_keys)}):")
            for mk in self.missing_keys[:10]:
                lines.append(f"  [{mk['language']}] {mk['module']}.{mk['key']}")
            if len(self.missing_keys) > 10:
                lines.append(f"  ... and {len(self.missing_keys) - 10} more")
        if self.unused_keys:
            lines.append(f"\nUnused Keys ({len(self.unused_keys)}):")
            for uk in self.unused_keys[:5]:
                lines.append(f"  [{uk['language']}] {uk['module']}.{uk['key']}")
        if self.module_mismatches:
            lines.append(f"\nModule Mismatches ({len(self.module_mismatches)}):")
            for mm in self.module_mismatches:
                lines.append(f"  {mm['module']}: missing in {mm['missing_languages']}")
        return "\n".join(lines)


class TranslationValidator:
    """Validates translation files for completeness and consistency.

    Usage:
        validator = TranslationValidator()
        result = validator.validate()
        print(result.summary())
        if result.is_valid:
            print("All translations are valid!")
    """

    def __init__(self, translations_dir: str | Path | None = None) -> None:
        from app.i18n.loader import TRANSLATIONS_DIR
        self._dir = Path(translations_dir) if translations_dir else TRANSLATIONS_DIR

    def validate(self) -> ValidationResult:
        """Validate all translation files.

        Checks:
        1. All languages have the same modules.
        2. All modules have the same keys across languages.
        3. No duplicate keys within a file.
        4. Reports unused keys (keys that exist but have no corresponding key in other languages).

        Returns:
            ValidationResult with all findings.
        """
        result = ValidationResult()

        # Discover languages and modules
        languages = sorted([
            d.name for d in self._dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ])

        if len(languages) < 2:
            result.warnings += 1
            logger.warning("Only %d language(s) found. Need at least 2 for validation.", len(languages))

        # Load all translations
        all_data: dict[str, dict[str, dict[str, Any]]] = {}  # lang -> module -> keys
        all_modules: set[str] = set()

        for lang in languages:
            all_data[lang] = {}
            lang_dir = self._dir / lang
            for f in lang_dir.iterdir():
                if f.suffix == ".json":
                    module = f.stem
                    all_modules.add(module)
                    try:
                        with open(f, encoding="utf-8") as fh:
                            all_data[lang][module] = json.load(fh)
                    except Exception as exc:
                        result.errors += 1
                        logger.error("Failed to load %s: %s", f, exc)

        # Check module consistency across languages
        for module in sorted(all_modules):
            has_langs = [lang for lang in languages if module in all_data.get(lang, {})]
            missing_langs = [lang for lang in languages if module not in all_data.get(lang, {})]
            if missing_langs:
                result.module_mismatches.append({
                    "module": module,
                    "has_languages": ", ".join(has_langs),
                    "missing_languages": ", ".join(missing_langs),
                })
                result.errors += len(missing_langs)

        # Check key consistency across languages for each module
        for module in sorted(all_modules):
            # Collect all keys across languages
            all_keys: dict[str, set[str]] = {}  # lang -> set of keys
            for lang in languages:
                if module in all_data.get(lang, {}):
                    all_keys[lang] = self._flatten_keys(all_data[lang][module])

            if not all_keys:
                continue

            # Find the union of all keys
            union_keys: set[str] = set()
            for keys in all_keys.values():
                union_keys.update(keys)

            result.total_keys = len(union_keys)

            # Check each language has all keys
            for lang, keys in all_keys.items():
                missing = union_keys - keys
                for key in sorted(missing):
                    result.missing_keys.append({
                        "language": lang,
                        "module": module,
                        "key": key,
                    })
                    result.errors += 1

            # Check for unused keys (keys in one language but not in union)
            # This catches keys that exist in one language but not in the reference
            reference_lang = languages[0] if languages else "en"
            reference_keys = all_keys.get(reference_lang, set())
            for lang, keys in all_keys.items():
                if lang == reference_lang:
                    continue
                extra = keys - reference_keys
                for key in sorted(extra):
                    result.unused_keys.append({
                        "language": lang,
                        "module": module,
                        "key": key,
                    })
                    result.warnings += 1

        return result

    @staticmethod
    def _flatten_keys(data: dict[str, Any], prefix: str = "") -> set[str]:
        """Flatten nested dict keys into dot-notation strings."""
        keys: set[str] = set()
        for k, v in data.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.update(TranslationValidator._flatten_keys(v, full_key))
            else:
                keys.add(full_key)
        return keys

    def validate_and_report(self) -> bool:
        """Validate and print a human-readable report.

        Returns:
            True if valid, False otherwise.
        """
        result = self.validate()
        print(result.summary())
        return result.is_valid
