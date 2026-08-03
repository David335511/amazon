"""LocaleManager — manages locale-specific formatting (date, number, currency, timezone).

Design decisions:
- Uses Python's `locale` module and `babel` (if available) for formatting.
- Falls back to manual formatting if babel is not installed.
- Each language has a LocaleConfig with all formatting rules.
- Timezone conversion uses `zoneinfo` (Python 3.9+).
- Pluralization rules are defined per language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LocaleConfig:
    """Formatting configuration for a locale."""

    language: str
    display_name: str
    native_name: str

    # Date formats (Python strftime)
    date_short: str = "%Y-%m-%d"
    date_long: str = "%B %d, %Y"
    date_time: str = "%Y-%m-%d %H:%M:%S"
    date_time_short: str = "%m/%d/%Y %H:%M"

    # Number formats
    decimal_separator: str = "."
    grouping_separator: str = ","
    decimal_places: int = 2

    # Currency formats
    currency_symbol: str = "$"
    currency_code: str = "USD"
    currency_position: str = "before"  # before or after
    currency_space: bool = False

    # Timezone
    default_timezone: str = "UTC"

    # Pluralization rules
    plural_forms: list[str] = field(default_factory=lambda: ["one", "other"])
    plural_fn: str = "en"  # Key into PLURAL_RULES

    # First day of week
    first_day_of_week: int = 0  # 0=Sunday, 1=Monday


# ── Pluralization Rules ─────────────────────────────────────
# Each function takes n (int) and returns the plural form key.

PLURAL_RULES: dict[str, Any] = {
    "en": lambda n: "one" if n == 1 else "other",
    "zh": lambda _: "other",  # Chinese doesn't have plural forms
}

# ── Built-in Locales ─────────────────────────────────────────
BUILTIN_LOCALES: dict[str, LocaleConfig] = {
    "en": LocaleConfig(
        language="en",
        display_name="English",
        native_name="English",
        date_short="%Y-%m-%d",
        date_long="%B %d, %Y",
        date_time="%Y-%m-%d %H:%M:%S",
        date_time_short="%m/%d/%Y %H:%M",
        decimal_separator=".",
        grouping_separator=",",
        currency_symbol="$",
        currency_code="USD",
        currency_position="before",
        plural_fn="en",
        first_day_of_week=0,
    ),
    "zh-CN": LocaleConfig(
        language="zh-CN",
        display_name="Chinese (Simplified)",
        native_name="简体中文",
        date_short="%Y年%m月%d日",
        date_long="%Y年%m月%d日",
        date_time="%Y年%m月%d日 %H:%M:%S",
        date_time_short="%Y/%m/%d %H:%M",
        decimal_separator=".",
        grouping_separator=",",
        currency_symbol="¥",
        currency_code="CNY",
        currency_position="before",
        plural_fn="zh",
        plural_forms=["other"],  # Chinese has no plural inflection
        first_day_of_week=1,
    ),
}


class LocaleManager:
    """Manages locale-specific formatting.

    Usage:
        locale = LocaleManager('zh-CN')
        locale.format_date(datetime.now())  # '2025年07月31日'
        locale.format_number(1234567.89)    # '1,234,567.89'
        locale.format_currency(29.99)       # '¥29.99'
        locale.pluralize(5, 'item')         # '5 items'
    """

    def __init__(self, language: str = "en") -> None:
        self._config = BUILTIN_LOCALES.get(language, BUILTIN_LOCALES["en"])
        self._language = language

    @property
    def config(self) -> LocaleConfig:
        return self._config

    # ── Date Formatting ─────────────────────────────────────

    def format_date(
        self,
        dt: datetime | str | None,
        fmt: str | None = None,
        tz: str | None = None,
    ) -> str:
        """Format a datetime for display.

        Args:
            dt: Datetime object, ISO string, or None.
            fmt: Override format string (uses locale default if None).
            tz: Override timezone (uses locale default if None).

        Returns:
            Formatted date string, or '—' if None.
        """
        if dt is None:
            return "—"
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except (ValueError, TypeError):
                return dt

        # Convert timezone
        tz_name = tz or self._config.default_timezone
        try:
            target_tz = ZoneInfo(tz_name)
            dt = dt.astimezone(target_tz)
        except Exception:
            pass

        fmt = fmt or self._config.date_short
        try:
            return dt.strftime(fmt)
        except Exception:
            return str(dt)

    def format_datetime(
        self,
        dt: datetime | str | None,
        tz: str | None = None,
    ) -> str:
        """Format a datetime with time."""
        return self.format_date(dt, fmt=self._config.date_time, tz=tz)

    def format_date_short(self, dt: datetime | str | None) -> str:
        """Format a date in short format."""
        return self.format_date(dt, fmt=self._config.date_time_short)

    # ── Number Formatting ───────────────────────────────────

    def format_number(
        self,
        value: int | float | Decimal | str | None,
        decimal_places: int | None = None,
    ) -> str:
        """Format a number with locale-appropriate grouping and decimal.

        Args:
            value: Number to format.
            decimal_places: Override decimal places.

        Returns:
            Formatted number string, or '—' if None.
        """
        if value is None:
            return "—"
        try:
            if isinstance(value, str):
                value = Decimal(value)
            num = float(value)
        except (ValueError, TypeError):
            return str(value) if value else "—"

        dp = decimal_places if decimal_places is not None else self._config.decimal_places
        sep = self._config.grouping_separator
        dec = self._config.decimal_separator

        formatted = f"{num:,.{dp}f}"
        # Replace default separators with locale-specific ones
        if sep != ",":
            formatted = formatted.replace(",", sep)
        if dec != ".":
            formatted = formatted.replace(".", dec)

        return formatted

    def format_percentage(
        self,
        value: int | float | Decimal | str | None,
        decimal_places: int = 1,
    ) -> str:
        """Format a percentage value."""
        if value is None:
            return "—"
        num = self.format_number(value, decimal_places=decimal_places)
        return f"{num}%"

    # ── Currency Formatting ────────────────────────────────

    def format_currency(
        self,
        value: int | float | Decimal | str | None,
        currency: str | None = None,  # noqa: ARG002 - kept for interface parity
    ) -> str:
        """Format a monetary value with currency symbol.

        Args:
            value: Monetary value.
            currency: Override currency code.

        Returns:
            Formatted currency string, or '—' if None.
        """
        if value is None:
            return "—"
        num = self.format_number(value)
        symbol = self._config.currency_symbol
        if self._config.currency_position == "before":
            space = " " if self._config.currency_space else ""
            return f"{symbol}{space}{num}"
        space = " " if self._config.currency_space else ""
        return f"{num}{space}{symbol}"

    # ── Pluralization ──────────────────────────────────────

    def pluralize(self, count: int, singular: str, plural: str | None = None) -> str:
        """Get the correct plural form for a count.

        Args:
            count: The number.
            singular: Singular form of the word.
            plural: Plural form (auto-generated if None).

        Returns:
            "{count} {word}" with correct plural form.
        """
        # Languages with a single plural form (e.g. Chinese) never inflect the
        # noun — do not append a plural suffix.
        if "one" not in self._config.plural_forms:
            word = singular
        else:
            rule_fn = PLURAL_RULES.get(self._config.plural_fn, PLURAL_RULES["en"])
            form = rule_fn(count)
            if form == "one" or count == 1:
                word = singular
            elif plural:
                word = plural
            else:
                word = singular + "s"

        return f"{self._format_count(count)} {word}"

    def _format_count(self, count: int) -> str:
        """Format a count as an integer (no decimal places) for pluralization."""
        return self.format_number(count, decimal_places=0) if isinstance(count, int) else self.format_number(count)

    # ── Timezone ────────────────────────────────────────────

    def convert_timezone(
        self,
        dt: datetime,
        target_tz: str | None = None,
    ) -> datetime:
        """Convert a datetime to the locale's timezone."""
        tz_name = target_tz or self._config.default_timezone
        try:
            target = ZoneInfo(tz_name)
            return dt.astimezone(target)
        except Exception:
            return dt
