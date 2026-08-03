"""Multilingual AI support — request/response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.assistant.models import AssistantResponse

# ──────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────


class DetectRequest(BaseModel):
    """A request to detect the language of a text."""

    text: str = Field(..., min_length=1, max_length=5000, description="Text to detect")
    supported_languages: list[str] | None = Field(
        None, description="Optional language whitelist (defaults to configured)",
    )


# ──────────────────────────────────────────────────────────────
# Structured localized content
# ──────────────────────────────────────────────────────────────


class LocalizedColumn(BaseModel):
    """A localized table column header."""

    key: str = Field(..., description="Column key (API field name — stays English)")
    label: str = Field(..., description="Localized display label")
    format: str = Field(default="text", description="text|number|currency|percentage")


class LocalizedTable(BaseModel):
    """A localized table (headers + formatted cells)."""

    title: str = Field(..., description="Localized title")
    columns: list[LocalizedColumn] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(
        default_factory=list, description="Localized/formatted cell values",
    )


class LocalizedChart(BaseModel):
    """A localized chart (title, axes, category labels, series)."""

    title: str = Field(..., description="Localized title")
    x_axis: str = Field(default="")
    y_axis: str = Field(default="")
    labels: list[str] = Field(default_factory=list, description="Category labels")
    series: list[dict[str, Any]] = Field(
        default_factory=list, description="Series names (localized) + formatted data",
    )
    currency: bool = Field(default=False)


class LocalizedRecommendation(BaseModel):
    """A localized recommendation."""

    action: str = Field(..., description="Localized action label")
    entity: str = Field(..., description="Entity identifier (ASIN/code — unchanged)")
    detail: str = Field(..., description="Localized detail")
    confidence: str | None = Field(None, description="Localized confidence")
    value: float | None = Field(None, description="Numeric value (unchanged)")


class LocalizedNotification(BaseModel):
    """A localized notification."""

    title: str = Field(..., description="Localized title")
    body: str = Field(..., description="Localized body")
    severity: str | None = Field(None, description="Localized severity")
    timestamp: str | None = Field(None, description="Timestamp (unchanged)")


class LocalizedReport(BaseModel):
    """A localized report."""

    title: str = Field(..., description="Localized title")
    sections: list[dict[str, str]] = Field(
        default_factory=list, description="Localized heading/content sections",
    )
    generated: str | None = Field(None, description="Generated timestamp")


class LocalizedEmail(BaseModel):
    """A localized email."""

    subject: str = Field(..., description="Localized subject")
    body: str = Field(..., description="Localized body")
    greeting: str = Field(default="Hello,")
    signature: str = Field(default="Amazon AI Commerce Platform")


# ──────────────────────────────────────────────────────────────
# Localization requests
# ──────────────────────────────────────────────────────────────


class ColumnSpec(BaseModel):
    key: str
    label: str = Field(..., description="Literal label or 't:module.key' reference")
    format: str = Field(default="text")


class LocalizeTableRequest(BaseModel):
    language: str | None = None
    title_key: str
    columns: list[ColumnSpec]
    rows: list[dict[str, Any]]


class ChartSeries(BaseModel):
    name: str = Field(..., description="Literal name or 't:module.key' reference")
    data: list[float] = Field(default_factory=list)


class LocalizeChartRequest(BaseModel):
    language: str | None = None
    title_key: str
    x_axis_key: str | None = None
    y_axis_key: str | None = None
    labels: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    currency: bool = False


class LocalizeRecommendationRequest(BaseModel):
    language: str | None = None
    action: str
    entity: str
    detail: str
    confidence: str | None = None
    value: float | None = None


class LocalizeNotificationRequest(BaseModel):
    language: str | None = None
    title: str
    body: str
    severity: str | None = None
    timestamp: str | None = None


class LocalizeReportRequest(BaseModel):
    language: str | None = None
    title: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    generated: str | None = None


class LocalizeEmailRequest(BaseModel):
    language: str | None = None
    subject: str
    body: str


class LocalizeAssistantRequest(BaseModel):
    language: str | None = Field(None, description="Target language (defaults to en)")
    response: AssistantResponse


# ──────────────────────────────────────────────────────────────
# Capabilities
# ──────────────────────────────────────────────────────────────


class MultilingualCapabilities(BaseModel):
    enabled: bool
    default_language: str
    supported_languages: list[str]
    llm_translate: bool
    prompt_inject_language: bool
    detection_supported: bool = True


class LanguageChangeResult(BaseModel):
    status: str
    language: str
    display_name: str | None = None
    native_name: str | None = None
    future_responses_use: str = Field(
        ..., description="Language all future responses will use",
    )
