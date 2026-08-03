"""Tests for the internationalization (i18n) system.

Covers the loader, cache, service (translation + interpolation + fallback),
locale manager (date / number / currency / timezone / pluralization),
validator (missing / unused / duplicate keys), language switcher (resolution +
browser/database/profile persistence), the manager facade, and the API.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.i18n.cache import TranslationCache
from app.i18n.config import I18nConfig
from app.i18n.loader import TranslationLoader
from app.i18n.locale import LocaleManager
from app.i18n.manager import I18nManager
from app.i18n.repository import I18nRepository
from app.i18n.service import TranslationService
from app.i18n.switcher import LanguageSwitcher
from app.i18n.validator import TranslationValidator

# ──────────────────────────────────────────────────────────────
# TranslationLoader
# ──────────────────────────────────────────────────────────────


def test_loader_discovers_languages() -> None:
    loader = TranslationLoader()
    langs = loader.list_languages()
    assert "en" in langs
    assert "zh-CN" in langs


def test_loader_discovers_all_modules() -> None:
    loader = TranslationLoader()
    modules = set(loader.list_modules("en"))
    assert {
        "common", "dashboard", "products", "analytics", "settings", "agent", "assistant",
    } <= modules


def test_loader_loads_json() -> None:
    loader = TranslationLoader()
    data = loader.load("en", "dashboard")
    assert data["title"] == "Product Intelligence Dashboard"


def test_loader_loads_missing_module_empty() -> None:
    loader = TranslationLoader()
    assert loader.load("en", "does_not_exist") == {}


def test_loader_language_exists() -> None:
    loader = TranslationLoader()
    assert loader.language_exists("en")
    assert not loader.language_exists("xx")


# ──────────────────────────────────────────────────────────────
# TranslationService
# ──────────────────────────────────────────────────────────────


def test_service_translates_en() -> None:
    svc = TranslationService("en")
    assert svc.t("dashboard.title") == "Product Intelligence Dashboard"


def test_service_translates_zh() -> None:
    svc = TranslationService("zh-CN")
    assert svc.t("dashboard.title") == "智能选品仪表盘"
    assert svc.language == "zh-CN"


def test_service_interpolation() -> None:
    svc = TranslationService("en")
    assert svc.t("common.pagination.page", page=3) == "Page 3"
    assert svc.t("common.pagination.page_of", page=2, total=10) == "Page 2 of 10"


def test_service_falls_back_to_key() -> None:
    svc = TranslationService("en")
    assert svc.t("nonexistent.deep.key") == "nonexistent.deep.key"


def test_service_default_override() -> None:
    svc = TranslationService("en")
    assert svc.t("missing.key", default="fallback text") == "fallback text"


def test_service_switch_language() -> None:
    svc = TranslationService("en")
    svc.switch_language("zh-CN")
    assert svc.language == "zh-CN"
    assert svc.t("dashboard.title") == "智能选品仪表盘"


def test_service_nested_access() -> None:
    svc = TranslationService("en")
    assert svc.t("products.fields.asin") == "ASIN"
    assert svc.t("agent.roles.planner") == "Planner"


def test_service_get_module_and_all() -> None:
    svc = TranslationService("en")
    mod = svc.get_module("common")
    assert mod["app"]["name"].startswith("Amazon")
    all_data = svc.get_all()
    assert "dashboard" in all_data and "assistant" in all_data


def test_service_translate_dict() -> None:
    svc = TranslationService("en")
    out = svc.translate_dict({"title": "t:dashboard.title", "nested": {"x": "t:common.status.active"}})
    assert out["title"] == "Product Intelligence Dashboard"
    assert out["nested"]["x"] == "Active"


# ──────────────────────────────────────────────────────────────
# LocaleManager — pluralization, date, number, currency, timezone
# ──────────────────────────────────────────────────────────────


def test_pluralize_en() -> None:
    lm = LocaleManager("en")
    assert lm.pluralize(1, "item") == "1 item"
    assert lm.pluralize(5, "item") == "5 items"


def test_pluralize_zh_no_suffix() -> None:
    lm = LocaleManager("zh-CN")
    # Chinese never inflects the noun.
    assert lm.pluralize(1, "商品") == "1 商品"
    assert lm.pluralize(5, "商品") == "5 商品"


def test_number_formatting() -> None:
    lm = LocaleManager("en")
    assert lm.format_number(1234567.89) == "1,234,567.89"
    assert lm.format_percentage(0.234) == "0.2%"


def test_currency_formatting() -> None:
    assert LocaleManager("en").format_currency(1234.5) == "$1,234.50"
    assert LocaleManager("zh-CN").format_currency(1234.5) == "¥1,234.50"


def test_date_formatting() -> None:
    lm = LocaleManager("zh-CN")
    dt = datetime(2026, 8, 12, 15, 30, 0, tzinfo=UTC)
    assert lm.format_date(dt) == "2026年08月12日"


def test_timezone_conversion() -> None:
    lm = LocaleManager("en")
    dt = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)
    converted = lm.convert_timezone(dt, target_tz="UTC")
    assert converted == dt


def test_locale_handles_none() -> None:
    lm = LocaleManager("en")
    assert lm.format_date(None) == "—"
    assert lm.format_number(None) == "—"
    assert lm.format_currency(None) == "—"


# ──────────────────────────────────────────────────────────────
# TranslationCache
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_set_get_invalidate() -> None:
    cache = TranslationCache(redis=None)  # local fallback
    await cache.set("en", "dashboard", {"title": "X"})
    got = await cache.get("en", "dashboard")
    assert got == {"title": "X"}
    await cache.invalidate(language="en", module="dashboard")
    assert await cache.get("en", "dashboard") is None


# ──────────────────────────────────────────────────────────────
# TranslationValidator
# ──────────────────────────────────────────────────────────────


def test_validator_passes_real_translations() -> None:
    result = TranslationValidator().validate()
    assert result.is_valid is True
    assert result.missing_keys == []
    assert result.duplicate_keys == []
    assert result.module_mismatches == []


def _write(tmp_path, lang, module, data) -> None:
    d = tmp_path / lang
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{module}.json").write_text(json.dumps(data), encoding="utf-8")


def test_validator_detects_missing_keys(tmp_path) -> None:
    _write(tmp_path, "en", "common", {"a": "A", "b": "B"})
    _write(tmp_path, "zh-CN", "common", {"a": "甲"})  # missing 'b'
    result = TranslationValidator(tmp_path).validate()
    assert result.is_valid is False
    assert any(m["key"] == "b" and m["language"] == "zh-CN" for m in result.missing_keys)


def test_validator_detects_duplicate_keys(tmp_path) -> None:
    _write(tmp_path, "en", "common", {"a": "A"})
    _write(tmp_path, "zh-CN", "common", {"a": "甲"})
    # A JSON file with a duplicate key.
    (tmp_path / "en" / "dup.json").write_text(
        '{"x":"1","x":"2"}', encoding="utf-8",
    )
    (tmp_path / "zh-CN" / "dup.json").write_text('{"x":"1"}', encoding="utf-8")
    result = TranslationValidator(tmp_path).validate()
    assert result.is_valid is False
    assert any(d["key"] == "x" for d in result.duplicate_keys)


def test_validator_detects_module_mismatch(tmp_path) -> None:
    _write(tmp_path, "en", "common", {"a": "A"})
    _write(tmp_path, "en", "dashboard", {"t": "T"})
    _write(tmp_path, "zh-CN", "common", {"a": "甲"})  # missing dashboard module
    result = TranslationValidator(tmp_path).validate()
    assert result.is_valid is False
    assert any(m["module"] == "dashboard" for m in result.module_mismatches)


def test_validator_yaml_support(tmp_path) -> None:
    (tmp_path / "en").mkdir(parents=True)
    (tmp_path / "zh-CN").mkdir(parents=True)
    (tmp_path / "en" / "common.yaml").write_text("a: A\nb: B\n", encoding="utf-8")
    (tmp_path / "zh-CN" / "common.yaml").write_text("a: 甲\nb: 乙\n", encoding="utf-8")
    result = TranslationValidator(tmp_path).validate()
    assert result.is_valid is True


# ──────────────────────────────────────────────────────────────
# LanguageSwitcher — resolution + persistence
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_switcher_resolution_priority(db_session) -> None:
    switch = LanguageSwitcher(I18nRepository(db_session), config=I18nConfig())
    r = await switch.resolve(query="zh-CN", cookie="en", header="fr")
    assert r.language == "zh-CN" and r.source == "query"
    r = await switch.resolve(cookie="zh-CN", header="en")
    assert r.language == "zh-CN" and r.source == "cookie"
    r = await switch.resolve(header="zh-CN")
    assert r.language == "zh-CN" and r.source == "header"
    r = await switch.resolve()
    assert r.language == "en" and r.source == "default"


@pytest.mark.asyncio
async def test_switcher_persists_to_db_and_profile(db_session) -> None:
    from app.domain.models.sourcing import User, UserSettings

    user = User(email="i18n@test.com", username="i18n_test", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserSettings(user_id=user.id))
    await db_session.flush()

    switch = LanguageSwitcher(I18nRepository(db_session), config=I18nConfig(), session=db_session)
    persisted = await switch.switch("zh-CN", user_id=user.id, source="manual")
    assert persisted["database"] is True
    assert persisted["profile"] is True

    pref = await switch.get_preference(user_id=user.id)
    assert pref["language"] == "zh-CN"


@pytest.mark.asyncio
async def test_switcher_upserts_in_place(db_session) -> None:
    from sqlalchemy import select

    from app.domain.models.sourcing import User
    from app.i18n.models import LanguagePreference

    user = User(email="i18n2@test.com", username="i18n_test2", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    switch = LanguageSwitcher(I18nRepository(db_session), config=I18nConfig(), session=db_session)
    await switch.switch("zh-CN", user_id=user.id)
    await switch.switch("en", user_id=user.id)  # second switch -> upsert

    rows = (await db_session.execute(select(LanguagePreference))).scalars().all()
    assert len(rows) == 1
    assert rows[0].language == "en"


@pytest.mark.asyncio
async def test_switcher_rejects_unsupported(db_session) -> None:
    from app.i18n.errors import LanguageUnsupportedError

    switch = LanguageSwitcher(I18nRepository(db_session), config=I18nConfig())
    with pytest.raises(LanguageUnsupportedError):
        await switch.switch("fr")


# ──────────────────────────────────────────────────────────────
# I18nManager
# ──────────────────────────────────────────────────────────────


def _manager(db_session) -> I18nManager:
    return I18nManager(I18nRepository(db_session), config=I18nConfig(), session=db_session)


def test_manager_capabilities(db_session) -> None:
    mgr = _manager(db_session)
    caps = mgr.capabilities()
    assert caps.default_language == "en"
    assert "zh-CN" in caps.supported_languages
    assert "dashboard" in caps.modules


def test_manager_list_languages(db_session) -> None:
    mgr = _manager(db_session)
    langs = mgr.list_languages()
    assert langs.total >= 2
    zh = next(lang for lang in langs.languages if lang.code == "zh-CN")
    assert zh.native_name == "简体中文"


def test_manager_translate_and_format(db_session) -> None:
    mgr = _manager(db_session)
    assert mgr.translate("en", "dashboard.title") == "Product Intelligence Dashboard"
    fmt = mgr.format("zh-CN")
    assert fmt.currency == "¥1,234.56"
    # Chinese does not inflect the noun -> no plural suffix.
    assert fmt.plural_other == "5 item"


@pytest.mark.asyncio
async def test_manager_get_bundle_lazy_and_cached(db_session) -> None:
    mgr = _manager(db_session)
    bundle = await mgr.get_bundle("en")
    assert "dashboard" in bundle.modules
    assert bundle.total_keys > 0
    assert bundle.cached is False
    second = await mgr.get_bundle("en")
    assert second.cached is True


@pytest.mark.asyncio
async def test_manager_switch_and_validate_and_reload(db_session) -> None:
    mgr = _manager(db_session)
    result = await mgr.switch("zh-CN")
    assert result.language == "zh-CN"
    v = mgr.validate()
    assert v.is_valid is True
    rel = await mgr.reload()
    assert rel.reloaded is True
    assert rel.languages >= 2


@pytest.mark.asyncio
async def test_manager_stats(db_session) -> None:
    mgr = _manager(db_session)
    stats = await mgr.stats()
    assert stats.available_languages >= 2
    assert stats.total_modules >= 7
    assert stats.total_keys > 0


# ──────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_capabilities(client) -> None:
    resp = await client.get("/api/v1/i18n/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_language"] == "en"
    assert "zh-CN" in data["supported_languages"]
    assert "dashboard" in data["modules"]


@pytest.mark.asyncio
async def test_api_languages(client) -> None:
    resp = await client.get("/api/v1/i18n/languages")
    assert resp.status_code == 200
    codes = [item["code"] for item in resp.json()["languages"]]
    assert "en" in codes and "zh-CN" in codes


@pytest.mark.asyncio
async def test_api_current_language(client) -> None:
    resp = await client.get("/api/v1/i18n/current", params={"lang": "zh-CN"})
    assert resp.status_code == 200
    assert resp.json()["language"] == "zh-CN"


@pytest.mark.asyncio
async def test_api_switch_sets_cookie(client) -> None:
    resp = await client.post("/api/v1/i18n/switch", params={"language": "zh-CN"})
    assert resp.status_code == 200
    assert resp.json()["language"] == "zh-CN"
    assert "zh-CN" in resp.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_api_switch_rejects_unsupported(client) -> None:
    resp = await client.post("/api/v1/i18n/switch", params={"language": "fr"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_api_bundle(client) -> None:
    resp = await client.get("/api/v1/i18n/bundle", params={"language": "zh-CN"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "zh-CN"
    assert "dashboard" in data["modules"]
    assert data["modules"]["dashboard"]["title"] == "智能选品仪表盘"


@pytest.mark.asyncio
async def test_api_translations_module(client) -> None:
    resp = await client.get("/api/v1/i18n/translations/dashboard", params={"language": "en"})
    assert resp.status_code == 200
    assert resp.json()["module"] == "dashboard"
    assert resp.json()["translations"]["title"] == "Product Intelligence Dashboard"


@pytest.mark.asyncio
async def test_api_locale_formatting(client) -> None:
    resp = await client.get("/api/v1/i18n/locale/zh-CN")
    assert resp.status_code == 200
    assert resp.json()["currency"].startswith("¥")


@pytest.mark.asyncio
async def test_api_validate_and_reload(client) -> None:
    resp = await client.post("/api/v1/i18n/validate")
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True
    rel = await client.post("/api/v1/i18n/reload")
    assert rel.status_code == 200
    assert rel.json()["reloaded"] is True


@pytest.mark.asyncio
async def test_api_stats(client) -> None:
    resp = await client.get("/api/v1/i18n/stats")
    assert resp.status_code == 200
    assert resp.json()["available_languages"] >= 2
