"""TranslationValidator — validates translation completeness and consistency.

Checks:
- **missing** translations — a key present in some languages but not others.
- **unused** translations — a key present in a language but not in the reference
  language, and (optionally) keys never referenced anywhere in the application
  code.
- **duplicate** keys — the same key defined more than once within a single file
  (JSON via ``object_pairs_hook``, YAML via a duplicate-aware loader).
- **module mismatches** — a module present in some languages but not others.

Both JSON (``.json``) and YAML (``.yaml`` / ``.yml``) files are supported. Every
translation key must exist in every language.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# Matches translation key references in source:  t('module.key'), t("a.b", ...),
# t:module.key, translate('a.b'), and common.app-style keys.
KEY_REFERENCE_RE = re.compile(
    r"(?P<fn>\bt|\btranslate|t:)\s*\(\s*['\"](?P<key>[A-Za-z0-9_.]+)['\"]",
)
MODULE_FILE_SUFFIXES = (".json", ".yaml", ".yml")


class DuplicateKeyError(Exception):
    """Raised when a translation file contains a duplicate key."""


class _JsonDupHook:
    """``object_pairs_hook`` that records duplicate keys within a JSON object."""

    def __init__(self, duplicates: list[str]) -> None:
        self._duplicates = duplicates

    def __call__(self, pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                self._duplicates.append(str(key))
            else:
                result[key] = value
        return result


def _yaml_load_unique(path: Path) -> dict[str, Any]:
    """Load a YAML file, raising on duplicate keys."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - pyyaml expected
        raise DuplicateKeyError(f"PyYAML not installed to load {path}") from exc

    class _UniqueLoader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict:
        mapping: dict = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise DuplicateKeyError(str(key))
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _UniqueLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping,
    )
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_UniqueLoader) or {}


def _load_file(path: Path, duplicates: list[str]) -> dict[str, Any]:
    """Load a JSON or YAML translation file, collecting duplicate keys."""
    if path.suffix == ".json":
        with open(path, encoding="utf-8") as fh:
            return json.load(fh, object_pairs_hook=_JsonDupHook(duplicates))
    return _yaml_load_unique(path)


class ValidationResult:
    """Result of a translation validation."""

    def __init__(self) -> None:
        self.missing_keys: list[dict[str, str]] = []   # {language, module, key}
        self.unused_keys: list[dict[str, str]] = []    # {language, module, key}
        self.duplicate_keys: list[dict[str, str]] = []  # {language, module, key}
        self.module_mismatches: list[dict[str, str]] = []  # {module, has_languages, missing_languages}
        self.total_keys: int = 0
        self.errors: int = 0
        self.warnings: int = 0

    @property
    def is_valid(self) -> bool:
        return self.errors == 0

    def summary(self) -> str:
        lines = [
            "Translation Validation Report",
            "=" * 40,
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
        if self.duplicate_keys:
            lines.append(f"\nDuplicate Keys ({len(self.duplicate_keys)}):")
            for dk in self.duplicate_keys[:10]:
                lines.append(f"  [{dk['language']}] {dk['module']}.{dk['key']}")
            if len(self.duplicate_keys) > 10:
                lines.append(f"  ... and {len(self.duplicate_keys) - 10} more")
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
    """Validates translation files for completeness and consistency."""

    def __init__(self, translations_dir: str | Path | None = None) -> None:
        from app.i18n.loader import TRANSLATIONS_DIR
        self._dir = Path(translations_dir) if translations_dir else TRANSLATIONS_DIR

    # ── Validation ────────────────────────────────────────────────────────

    def validate(self) -> ValidationResult:
        """Validate all translation files across all languages.

        Checks:
        1. All languages have the same modules.
        2. No duplicate keys within a file.
        3. All modules have the same keys across languages.
        4. Reports unused keys (present in a language but not the reference).
        """
        result = ValidationResult()

        languages = sorted([
            d.name for d in self._dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ])
        if len(languages) < 2:
            result.warnings += 1
            logger.warning("Only %d language(s) found. Need at least 2 for validation.", len(languages))

        all_data: dict[str, dict[str, dict[str, Any]]] = {}
        all_modules: set[str] = set()

        for lang in languages:
            all_data[lang] = {}
            lang_dir = self._dir / lang
            for f in sorted(lang_dir.iterdir()):
                if f.suffix not in MODULE_FILE_SUFFIXES:
                    continue
                module = f.stem
                all_modules.add(module)
                duplicates: list[str] = []
                try:
                    data = _load_file(f, duplicates)
                    all_data[lang][module] = data
                except DuplicateKeyError as exc:
                    result.errors += 1
                    result.duplicate_keys.append({
                        "language": lang, "module": module, "key": str(exc),
                    })
                    all_data[lang][module] = {}
                except Exception as exc:
                    result.errors += 1
                    logger.error("Failed to load %s: %s", f, exc)
                    all_data[lang][module] = {}
                # Report any duplicates collected during JSON load.
                for dup in duplicates:
                    result.duplicate_keys.append({
                        "language": lang, "module": module, "key": dup,
                    })
                    result.errors += 1

        # Module consistency across languages.
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

        # Key consistency across languages for each module.
        all_keys: dict[str, dict[str, set[str]]] = {}  # module -> lang -> keys
        for module in sorted(all_modules):
            module_keys: dict[str, set[str]] = {}
            for lang in languages:
                if module in all_data.get(lang, {}):
                    module_keys[lang] = self._flatten_keys(all_data[lang][module])
            all_keys[module] = module_keys
            if not module_keys:
                continue

            union: set[str] = set()
            for keys in module_keys.values():
                union.update(keys)
            result.total_keys = len(union)

            for lang, keys in module_keys.items():
                missing = union - keys
                for key in sorted(missing):
                    result.missing_keys.append({
                        "language": lang, "module": module, "key": key,
                    })
                    result.errors += 1

            # Unused: keys present in a non-reference language but not in the reference.
            reference_lang = languages[0] if languages else "en"
            reference_keys = module_keys.get(reference_lang, set())
            for lang, keys in module_keys.items():
                if lang == reference_lang:
                    continue
                for key in sorted(keys - reference_keys):
                    result.unused_keys.append({
                        "language": lang, "module": module, "key": key,
                    })
                    result.warnings += 1

        return result

    # ── Code-usage scan ───────────────────────────────────────────────────

    def scan_code_usage(self, source_dir: str | Path | None = None) -> dict[str, Any]:
        """Scan application source for translation-key references.

        Reports:
        - ``referenced_keys`` — every module.key referenced anywhere in source.
        - ``defined_keys`` — every translation key currently defined.
        - ``defined_but_unused`` — defined keys never referenced in source.
        - ``used_but_missing`` — referenced keys that have no definition.

        Returns a dict suitable for CI/CD.
        """
        root = Path(source_dir) if source_dir else self._dir.parent
        referenced: set[str] = set()
        for py in root.rglob("*.py"):
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:  # pragma: no cover
                continue
            for match in KEY_REFERENCE_RE.finditer(text):
                referenced.add(match.group("key"))

        defined: set[str] = set()
        for _module, lang_keys in self._collect_all().items():
            for keys in lang_keys.values():
                defined.update(keys)

        return {
            "referenced_keys": sorted(referenced),
            "defined_keys": sorted(defined),
            "defined_but_unused": sorted(defined - referenced),
            "used_but_missing": sorted(referenced - defined),
            "referenced_count": len(referenced),
            "defined_count": len(defined),
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    def _collect_all(self) -> dict[str, dict[str, set[str]]]:
        """Return {module: {language: set(keys)}} for every translation file."""
        out: dict[str, dict[str, set[str]]] = {}
        for lang_dir in self._dir.iterdir():
            if not lang_dir.is_dir() or lang_dir.name.startswith("."):
                continue
            lang = lang_dir.name
            for f in lang_dir.iterdir():
                if f.suffix not in MODULE_FILE_SUFFIXES:
                    continue
                data = _load_file(f, [])
                out.setdefault(f.stem, {}).setdefault(lang, set()).update(
                    self._flatten_keys(data)
                )
        return out

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
        """Validate and print a human-readable report."""
        result = self.validate()
        print(result.summary())
        return result.is_valid
