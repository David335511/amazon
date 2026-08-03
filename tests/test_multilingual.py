"""Tests for the multilingual AI subsystem.

Covers language detection, deterministic localization (labels, contexts, charts,
tables, recommendations, notifications, reports, emails), prompt injection,
LLM prose translation (fake provider), the manager facade, the API, and the
assistant-engine integration (responses in the selected language).
"""

from __future__ import annotations

import pytest

from app.ai.base import LLMConfig, LLMProvider, LLMResponse
from app.assistant.engine import AssistantEngine
from app.assistant.models import (
    AssistantCapability,
    AssistantQuery,
    AssistantResponse,
    DataSource,
    RetrievedContext,
)
from app.i18n import I18nConfig, I18nManager, I18nRepository
from app.i18n.service import TranslationService
from app.multilingual import localize as L  # noqa: N812
from app.multilingual.config import MultilingualConfig
from app.multilingual.detection import detect_language
from app.multilingual.errors import UnsupportedLanguageError
from app.multilingual.manager import MultilingualManager

# ──────────────────────────────────────────────────────────────
# Detection (pure, offline)
# ──────────────────────────────────────────────────────────────


def test_detect_chinese() -> None:
    r = detect_language("为什么这个商品有利润？", supported=["en", "zh-CN"])  # noqa: RUF001
    assert r.detected_language == "zh-CN"
    assert r.script == "cjk"
    assert r.confidence > 0.5


def test_detect_english() -> None:
    r = detect_language("Why is this product profitable today?", supported=["en", "zh-CN"])
    assert r.detected_language == "en"
    assert r.script == "latin"


def test_detect_empty_falls_back() -> None:
    r = detect_language("", default="en")
    assert r.detected_language == "en"
    assert r.script == "unknown"
    assert r.confidence == 0.0


def test_detect_ambiguous_short_token() -> None:
    # An ASIN is all Latin letters/digits -> detected as English (latin script).
    r = detect_language("B0TEST1234", default="en")
    assert r.detected_language == "en"
    assert r.script == "latin"
    assert r.confidence > 0.5


def test_detect_unsupported_script() -> None:
    # Cyrillic is not in our whitelist -> default.
    r = detect_language("почему это выгодно", supported=["en", "zh-CN"], default="en")
    assert r.detected_language == "en"
    assert r.script == "unknown"


# ──────────────────────────────────────────────────────────────
# Deterministic localization (pure functions via TranslationService)
# ──────────────────────────────────────────────────────────────


def _zh() -> TranslationService:
    return TranslationService("zh-CN")


def test_localize_confidence_zh() -> None:
    assert L.localize_confidence("high", _zh()) == "高"
    assert L.localize_confidence("very_low", _zh()) == "非常低"


def test_localize_capability_zh() -> None:
    assert L.localize_capability(AssistantCapability.WHY_PROFITABLE, _zh()) == "盈利分析"
    assert L.localize_capability("find_similar", _zh()) == "相似商品"


def test_localize_trend_and_restock_zh() -> None:
    assert L.localize_trend("up", _zh()) == "上升"
    assert L.localize_restock("buy_now", _zh()) == "立即采购"


def test_localize_source_summary_preserves_data() -> None:
    ctx = RetrievedContext(
        source=DataSource.PROFIT_CALCULATIONS,
        summary="Net profit: $10.50/unit, ROI: 25.0%",
        data={"net_profit": 10.5},
        record_count=1,
    )
    out = L.localize_source_summary(ctx, _zh())
    assert out.startswith("利润计算:")
    assert "$10.50/unit" in out  # data preserved verbatim


def test_localize_contexts_preserves_source_enum() -> None:
    ctx = [RetrievedContext(
        source=DataSource.PROFIT_CALCULATIONS,
        summary="Net profit: $10.50/unit",
        record_count=1,
    )]
    out = L.localize_contexts(ctx, _zh())
    # API field name / enum value stays English.
    assert out[0].source == DataSource.PROFIT_CALCULATIONS
    assert out[0].summary.startswith("利润计算:")


def test_localize_table_formats_cells() -> None:
    table = L.localize_table(
        title_key="t:multilingual.labels.table",
        columns=[
            {"key": "product", "label": "t:multilingual.labels.product", "format": "text"},
            {"key": "price", "label": "t:multilingual.labels.price", "format": "currency"},
            {"key": "units", "label": "t:multilingual.labels.quantity", "format": "number"},
        ],
        rows=[{"product": "B0TEST", "price": 1234.5, "units": 5}],
        svc=_zh(), locale=_zh().locale,
    )
    assert table.title == "表格"
    assert table.columns[0].label == "商品"
    assert table.rows[0]["price"] == "¥1,234.50"  # locale currency
    assert table.rows[0]["product"] == "B0TEST"   # entity preserved


def test_localize_chart_and_email() -> None:
    chart = L.localize_chart(
        title_key="t:multilingual.labels.chart",
        x_axis_key="t:multilingual.labels.trend",
        y_axis_key="t:multilingual.labels.revenue",
        labels=["A"],
        series=[{"name": "t:multilingual.labels.product", "data": [1.5]}],
        svc=_zh(), locale=_zh().locale,
    )
    assert chart.title == "图表"
    assert chart.series[0]["name"] == "商品"

    email = L.localize_email(subject="Weekly report", body="Summary", svc=_zh())
    assert email.greeting == "您好，"  # noqa: RUF001


# ──────────────────────────────────────────────────────────────
# Manager
# ──────────────────────────────────────────────────────────────


def _mgr(i18n=None, config=None, llm=None) -> MultilingualManager:
    return MultilingualManager(i18n=i18n, config=config or MultilingualConfig(), llm_provider=llm)


def test_manager_capabilities() -> None:
    caps = _mgr().capabilities()
    assert caps.default_language == "en"
    assert "zh-CN" in caps.supported_languages
    assert caps.prompt_inject_language is True
    assert caps.llm_translate is False  # no LLM configured


def test_manager_language_name() -> None:
    mgr = _mgr()
    assert mgr.language_name("en") == "English"
    assert mgr.language_name("zh-CN") == "简体中文"
    assert mgr.normalize("fr") == "en"
    assert mgr.is_supported("zh-CN")


def test_manager_detect() -> None:
    r = _mgr().detect("这个商品利润很高")
    assert r.detected_language == "zh-CN"


def test_manager_build_system_instruction() -> None:
    mgr = _mgr()
    base = "You are a sourcing analyst."
    # en -> unchanged
    assert mgr.build_system_instruction(base, "en") == base
    zh = mgr.build_system_instruction(base, "zh-CN")
    # Instruction is written in English; asks for a reply in 简体中文.
    assert base in zh
    assert "简体中文" in zh
    assert "Reason in English" in zh


@pytest.mark.asyncio
async def test_manager_translate_text_no_llm_unchanged() -> None:
    mgr = _mgr()
    text = "The product is profitable."
    assert await mgr.translate_text(text, "zh-CN") == text  # deterministic fallback


class _FakeLLM(LLMProvider):
    provider_name = "fake"

    async def generate(self, system_prompt, user_prompt, *, config=None) -> LLMResponse:  # noqa: ARG002
        return LLMResponse(content="这是一个翻译", model="fake", provider="fake")

    async def is_available(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_manager_translate_text_with_llm() -> None:
    mgr = _mgr(llm=_FakeLLM(config=LLMConfig()))
    out = await mgr.translate_text("The product is profitable.", "zh-CN")
    assert out == "这是一个翻译"
    # en is a no-op even with an LLM.
    assert await mgr.translate_text("Profit high", "en") == "Profit high"


def test_manager_localize_response_labels() -> None:
    resp = AssistantResponse(
        answer="Some analysis", capability=AssistantCapability.WHY_PROFITABLE,
        confidence="high",
        contexts=[RetrievedContext(
            source=DataSource.PROFIT_CALCULATIONS, summary="$10.5/unit", record_count=1,
        )],
        provider_used="anthropic",
    )
    out = _mgr().localize_labels(resp, "zh-CN")
    assert out.language == "zh-CN"
    assert out.capability_label == "盈利分析"
    assert out.confidence_label == "高"
    assert out.capability == AssistantCapability.WHY_PROFITABLE  # enum stays English
    assert out.contexts[0].source == DataSource.PROFIT_CALCULATIONS


@pytest.mark.asyncio
async def test_manager_localize_response_translates_prose() -> None:
    mgr = _mgr(llm=_FakeLLM(config=LLMConfig()))
    resp = AssistantResponse(
        answer="The product is profitable.", capability=AssistantCapability.WHY_PROFITABLE,
        confidence="medium", provider_used="anthropic",
    )
    out = await mgr.localize_response(resp, "zh-CN")
    assert out.answer == "这是一个翻译"  # LLM prose translation
    assert out.language == "zh-CN"


def test_manager_fallback_answer_localized() -> None:
    mgr = _mgr()
    out = mgr.fallback_answer("why profitable", [], "zh-CN")
    assert "分析：" in out  # noqa: RUF001
    assert "未找到" in out


def test_manager_localize_table_chart_recommendation_email() -> None:
    mgr = _mgr()
    table = mgr.localize_table(
        title_key="t:multilingual.labels.table",
        columns=[{"key": "p", "label": "t:multilingual.labels.product", "format": "text"}],
        rows=[{"p": "B0"}], language="zh-CN",
    )
    assert table.columns[0].label == "商品"

    rec = mgr.localize_recommendation(
        action="t:multilingual.restock.buy_now", entity="B0TEST", detail="Low stock",
        language="zh-CN",
    )
    assert rec.action == "立即采购"
    assert rec.entity == "B0TEST"

    email = mgr.localize_email(subject="Weekly", body="Body", language="zh-CN")
    assert email.signature == "亚马逊 AI 商务平台"


@pytest.mark.asyncio
async def test_manager_change_language_persists(db_session) -> None:
    i18n = I18nManager(I18nRepository(db_session), config=I18nConfig(), session=db_session)
    mgr = _mgr(i18n=i18n)
    result = await mgr.change_language("zh-CN")
    assert result.status == "switched"
    assert result.language == "zh-CN"
    assert result.future_responses_use == "zh-CN"


@pytest.mark.asyncio
async def test_manager_change_language_rejects_unsupported() -> None:
    with pytest.raises(UnsupportedLanguageError):
        await _mgr().change_language("fr")


@pytest.mark.asyncio
async def test_manager_resolve_current_delegates(db_session) -> None:
    i18n = I18nManager(I18nRepository(db_session), config=I18nConfig(), session=db_session)
    mgr = _mgr(i18n=i18n)
    assert await mgr.resolve_current(query="zh-CN") == "zh-CN"
    assert await mgr.resolve_current() == "en"


# ──────────────────────────────────────────────────────────────
# Assistant engine integration
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_responds_in_selected_language(db_session) -> None:
    i18n = I18nManager(I18nRepository(db_session), config=I18nConfig(), session=db_session)
    mgr = _mgr(i18n=i18n)
    engine = AssistantEngine(db=db_session, multilingual=mgr, language="zh-CN")
    resp = await engine.answer(AssistantQuery(question="Why is this profitable?"))
    assert resp.language == "zh-CN"
    assert resp.provider_used == "fallback"
    assert resp.capability_label == "盈利分析"
    assert "分析：" in resp.answer  # noqa: RUF001


@pytest.mark.asyncio
async def test_engine_english_default(db_session) -> None:
    mgr = _mgr(i18n=I18nManager(I18nRepository(db_session), config=I18nConfig(), session=db_session))
    engine = AssistantEngine(db=db_session, multilingual=mgr, language="en")
    resp = await engine.answer(AssistantQuery(question="why profitable"))
    assert resp.language == "en"
    assert resp.capability_label == "Profitability analysis"


# ──────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_capabilities(client) -> None:
    resp = await client.get("/api/v1/multilingual/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_language"] == "en"
    assert "zh-CN" in data["supported_languages"]


@pytest.mark.asyncio
async def test_api_languages(client) -> None:
    resp = await client.get("/api/v1/multilingual/languages")
    assert resp.status_code == 200
    codes = [item["code"] for item in resp.json()["languages"]]
    assert "en" in codes and "zh-CN" in codes


@pytest.mark.asyncio
async def test_api_current(client) -> None:
    resp = await client.get("/api/v1/multilingual/current", params={"lang": "zh-CN"})
    assert resp.status_code == 200
    assert resp.json()["language"] == "zh-CN"


@pytest.mark.asyncio
async def test_api_change_language_sets_cookie(client) -> None:
    resp = await client.post("/api/v1/multilingual/language", params={"language": "zh-CN"})
    assert resp.status_code == 200
    assert resp.json()["language"] == "zh-CN"
    assert "zh-CN" in resp.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_api_change_language_rejects_unsupported(client) -> None:
    resp = await client.post("/api/v1/multilingual/language", params={"language": "fr"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_api_detect(client) -> None:
    resp = await client.post(
        "/api/v1/multilingual/detect", json={"text": "这个商品利润高吗？"},  # noqa: RUF001
    )
    assert resp.status_code == 200
    assert resp.json()["detected_language"] == "zh-CN"


@pytest.mark.asyncio
async def test_api_translate(client) -> None:
    resp = await client.post(
        "/api/v1/multilingual/translate",
        params={"language": "zh-CN", "text": "Profitable product"},
    )
    assert resp.status_code == 200
    assert resp.json()["language"] == "zh-CN"


@pytest.mark.asyncio
async def test_api_localize_response(client) -> None:
    payload = {
        "language": "zh-CN",
        "response": {
            "answer": "Profitable analysis.",
            "capability": "why_profitable",
            "confidence": "high",
            "contexts": [],
            "model_used": "x",
            "provider_used": "anthropic",
            "prompt_version": "assistant_v1",
        },
    }
    resp = await client.post("/api/v1/multilingual/localize/response", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "zh-CN"
    assert data["capability_label"] == "盈利分析"
    assert data["confidence_label"] == "高"


@pytest.mark.asyncio
async def test_api_localize_table(client) -> None:
    payload = {
        "language": "zh-CN",
        "title_key": "t:multilingual.labels.table",
        "columns": [{"key": "product", "label": "t:multilingual.labels.product", "format": "text"}],
        "rows": [{"product": "B0TEST"}],
    }
    resp = await client.post("/api/v1/multilingual/localize/table", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "表格"
    assert data["columns"][0]["label"] == "商品"


@pytest.mark.asyncio
async def test_api_localize_email(client) -> None:
    resp = await client.post(
        "/api/v1/multilingual/localize/email",
        json={"language": "zh-CN", "subject": "Weekly", "body": "Body"},
    )
    assert resp.status_code == 200
    assert resp.json()["signature"] == "亚马逊 AI 商务平台"
