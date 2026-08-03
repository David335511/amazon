"""Multilingual AI support — deterministic response localizers.

These pure functions localize *user-facing* content (labels, confidence, trends,
recommendations, charts, tables, notifications, reports, emails) into a target
language using the i18n translation service + locale formatters.

Design decisions:
- **Only display text is translated.** API field names, enum values, DB fields,
  codes, ASINs, SKUs and numeric values are never translated.
- Deterministic: the same input + language always produces the same output, so
  the localized content is reproducible even with no LLM configured.
- ``en`` is a supported no-op target: localizing to English returns idiomatic
  English labels.
"""

from __future__ import annotations

from typing import Any

from app.assistant.models import AssistantCapability, RetrievedContext
from app.i18n.service import TranslationService
from app.multilingual.schemas import (
    LocalizedChart,
    LocalizedColumn,
    LocalizedEmail,
    LocalizedNotification,
    LocalizedRecommendation,
    LocalizedReport,
    LocalizedTable,
)

# Translation-key prefixes used for the enumerated AI-output labels.
_CONFIDENCE_PREFIX = "multilingual.confidence."
_CAPABILITY_PREFIX = "multilingual.capability."
_DATA_SOURCE_PREFIX = "multilingual.data_source."
_TREND_PREFIX = "multilingual.trend."
_RESTOCK_PREFIX = "multilingual.restock."


def _value(v: Any, default: str = "") -> str:
    return v.value if hasattr(v, "value") else str(v or default)


# ──────────────────────────────────────────────────────────────
# Atomic labels
# ──────────────────────────────────────────────────────────────


def localize_confidence(confidence: str | Any, svc: TranslationService) -> str:
    """Localize a confidence level (very_high/high/...)."""
    return svc.t(_CONFIDENCE_PREFIX + _value(confidence), default=_value(confidence))


def localize_capability(
    capability: AssistantCapability | str, svc: TranslationService,
) -> str:
    """Localize an assistant capability label."""
    return svc.t(_CAPABILITY_PREFIX + _value(capability), default=_value(capability))


def localize_data_source(source: str | Any, svc: TranslationService) -> str:
    """Localize a data-source label (used in retrieved-context summaries)."""
    return svc.t(_DATA_SOURCE_PREFIX + _value(source), default=_value(source))


def localize_trend(trend: str, svc: TranslationService) -> str:
    """Localize a sales-trend direction (up/down/flat/seasonal)."""
    return svc.t(_TREND_PREFIX + trend, default=trend)


def localize_restock(recommendation: str, svc: TranslationService) -> str:
    """Localize a restock recommendation (buy_now/buy_soon/wait/emergency)."""
    return svc.t(_RESTOCK_PREFIX + recommendation, default=recommendation)


def localize_source_summary(context: RetrievedContext, svc: TranslationService) -> str:
    """Localize a retrieved-context summary.

    The localized data-source label is prefixed; the raw summary (numbers, codes,
    units) is preserved verbatim so data stays exact.
    """
    return f"{localize_data_source(context.source, svc)}: {context.summary}"


def localize_contexts(
    contexts: list[RetrievedContext], svc: TranslationService,
) -> list[RetrievedContext]:
    """Localize each retrieved context's display summary (data preserved)."""
    return [
        RetrievedContext(
            source=c.source,
            summary=localize_source_summary(c, svc),
            data=c.data,
            record_count=c.record_count,
        )
        for c in contexts
    ]


# ──────────────────────────────────────────────────────────────
# Structured content (charts, tables, recommendations, ...)
# ──────────────────────────────────────────────────────────────


def _column_label(col: dict[str, Any], svc: TranslationService) -> str:
    label = col.get("label", col["key"])
    if isinstance(label, str) and label.startswith("t:"):
        return svc.t(label[2:], default=label[2:])
    return label


def _format_cell(value: Any, fmt: str, locale) -> str:
    if value is None:
        return "—"
    if fmt == "number":
        return locale.format_number(value)
    if fmt == "currency":
        return locale.format_currency(value)
    if fmt == "percentage":
        return locale.format_percentage(value)
    return str(value)


def _ref(key: str | None, svc: TranslationService, default: str = "") -> str:
    """Translate a key that may be a 't:module.key' reference, else literal."""
    if key is None:
        return default
    if isinstance(key, str) and key.startswith("t:"):
        return svc.t(key[2:], default=key[2:])
    return key


def localize_table(
    *,
    title_key: str,
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    svc: TranslationService,
    locale,
) -> LocalizedTable:
    """Localize a table's title, column headers and formatted cells."""
    loc_columns = [
        LocalizedColumn(key=col["key"], label=_column_label(col, svc), format=col.get("format", "text"))
        for col in columns
    ]
    loc_rows: list[dict[str, str]] = []
    for row in rows:
        loc_rows.append({
            col["key"]: _format_cell(row.get(col["key"]), col.get("format", "text"), locale)
            for col in columns
        })
    return LocalizedTable(
        title=_ref(title_key, svc, default=title_key),
        columns=loc_columns,
        rows=loc_rows,
    )


def localize_chart(
    *,
    title_key: str,
    x_axis_key: str | None,
    y_axis_key: str | None,
    labels: list[str],
    series: list[dict[str, Any]],
    svc: TranslationService,
    locale,
    currency: bool = False,
) -> LocalizedChart:
    """Localize a chart's title, axes, category labels and series names."""
    loc_series = []
    for s in series:
        name = s["name"]
        if isinstance(name, str) and name.startswith("t:"):
            name = svc.t(name[2:], default=name[2:])
        data = [
            locale.format_currency(v) if currency else locale.format_number(v)
            for v in s.get("data", [])
        ]
        loc_series.append({"name": name, "data": data})
    return LocalizedChart(
        title=_ref(title_key, svc, default=title_key),
        x_axis=_ref(x_axis_key, svc) if x_axis_key else "",
        y_axis=_ref(y_axis_key, svc) if y_axis_key else "",
        labels=list(labels),
        series=loc_series,
        currency=currency,
    )


def localize_recommendation(
    *,
    action: str,
    entity: str,
    detail: str,
    svc: TranslationService,
    confidence: str | None = None,
    value: float | None = None,
) -> LocalizedRecommendation:
    """Localize a recommendation (action/detail labels; entity + value preserved)."""
    if isinstance(action, str) and action.startswith("t:"):
        action = svc.t(action[2:], default=action[2:])
    if isinstance(detail, str) and detail.startswith("t:"):
        detail = svc.t(detail[2:], default=detail[2:])
    return LocalizedRecommendation(
        action=action,
        entity=entity,
        detail=detail,
        confidence=localize_confidence(confidence, svc) if confidence else None,
        value=value,
    )


def localize_notification(
    *,
    title: str,
    body: str,
    svc: TranslationService,
    severity: str | None = None,
    timestamp: str | None = None,
) -> LocalizedNotification:
    if isinstance(title, str) and title.startswith("t:"):
        title = svc.t(title[2:], default=title[2:])
    if isinstance(body, str) and body.startswith("t:"):
        body = svc.t(body[2:], default=body[2:])
    return LocalizedNotification(
        title=title, body=body,
        severity=localize_confidence(severity, svc) if severity else None,
        timestamp=timestamp,
    )


def localize_report(
    *,
    title: str,
    sections: list[dict[str, Any]],
    svc: TranslationService,
    generated: str | None = None,
) -> LocalizedReport:
    if isinstance(title, str) and title.startswith("t:"):
        title = svc.t(title[2:], default=title[2:])
    loc_sections = []
    for section in sections:
        heading = section.get("heading", "")
        if isinstance(heading, str) and heading.startswith("t:"):
            heading = svc.t(heading[2:], default=heading[2:])
        loc_sections.append({
            "heading": heading,
            "content": section.get("content", ""),
        })
    return LocalizedReport(title=title, sections=loc_sections, generated=generated)


def localize_email(
    *,
    subject: str,
    body: str,
    svc: TranslationService,
    greeting_key: str = "multilingual.email.greeting",
    signature_key: str = "multilingual.email.signature",
) -> LocalizedEmail:
    if isinstance(subject, str) and subject.startswith("t:"):
        subject = svc.t(subject[2:], default=subject[2:])
    if isinstance(body, str) and body.startswith("t:"):
        body = svc.t(body[2:], default=body[2:])
    return LocalizedEmail(
        subject=subject,
        body=body,
        greeting=svc.t(greeting_key, default="Hello,"),
        signature=svc.t(signature_key, default="Amazon AI Commerce Platform"),
    )
