"""Multilingual AI support — manager facade.

`MultilingualManager` is the ONLY entry point for:
- resolving / changing the output language (delegating to i18n persistence),
- detecting the language of incoming text,
- injecting the selected language into LLM prompts (reasoning stays English),
- localizing user-facing content (assistant responses, charts, tables,
  recommendations, notifications, reports, emails) deterministically.

Design decisions:
- **Prompts remain English internally.** ``build_system_instruction`` appends an
  English instruction telling the model to write its final answer in the selected
  language while keeping codes, ASINs, SKUs and numbers verbatim.
- **Deterministic localization** for structured content via the i18n service and
  locale formatters — works with no LLM configured.
- **Optional LLM prose translation** when an LLM is configured and the assistant
  was not already prompted to reply in the target language.
- **Only user-facing text is translated**; DB fields, API field names, enum
  values, configuration, code, logs, SQL and JSON keys stay English.
"""

from __future__ import annotations

from typing import Any

from app.ai.base import LLMProvider
from app.assistant.models import AssistantResponse, RetrievedContext
from app.i18n import I18nManager
from app.i18n.locale import BUILTIN_LOCALES, LocaleManager
from app.i18n.service import TranslationService
from app.multilingual.config import MultilingualConfig
from app.multilingual.detection import DetectionResult, detect_language
from app.multilingual.errors import UnsupportedLanguageError
from app.multilingual.localize import (
    localize_capability,
    localize_chart,
    localize_confidence,
    localize_contexts,
    localize_email,
    localize_notification,
    localize_recommendation,
    localize_report,
    localize_source_summary,
    localize_table,
)
from app.multilingual.schemas import (
    LanguageChangeResult,
    LocalizedChart,
    LocalizedEmail,
    LocalizedNotification,
    LocalizedRecommendation,
    LocalizedReport,
    LocalizedTable,
    MultilingualCapabilities,
)

_TRANSLATE_SYSTEM = (
    "You are a precise translator. Translate the user's English text into the "
    "requested language. Keep every ASIN, SKU, product code, numeric value, unit "
    "price and proper noun exactly as-is. Do not translate codes or unit prices. "
    "Reason is not needed — return only the translation."
)


class MultilingualManager:
    """Facade over the multilingual AI subsystem."""

    def __init__(
        self,
        i18n: I18nManager | None = None,
        config: MultilingualConfig | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self._i18n = i18n
        self._config = config or MultilingualConfig()
        self._llm = llm_provider

    # ── Capabilities ────────────────────────────────────────────

    @property
    def config(self) -> MultilingualConfig:
        return self._config

    def capabilities(self) -> MultilingualCapabilities:
        return MultilingualCapabilities(
            enabled=self._config.enabled,
            default_language=self._config.default_language,
            supported_languages=list(self._config.supported_languages),
            llm_translate=self._config.llm_translate and self._llm is not None,
            prompt_inject_language=self._config.prompt_inject_language,
        )

    def available_languages(self):
        """Return the list of supported output languages."""
        if self._i18n is not None:
            return self._i18n.list_languages()
        from app.i18n.locale import BUILTIN_LOCALES as _B

        return [
            {"code": c, "display_name": _B.get(c).display_name if _B.get(c) else c,
             "native_name": _B.get(c).native_name if _B.get(c) else c}
            for c in self._config.supported_languages
        ]

    def is_supported(self, language: str) -> bool:
        return language in self._config.supported_languages

    def normalize(self, language: str | None) -> str:
        """Return a supported language code (falls back to default)."""
        return self._normalize(language)

    def language_name(self, language: str) -> str:
        """Return the native name of a language (used in prompts / labels)."""
        cfg = BUILTIN_LOCALES.get(language)
        return cfg.native_name if cfg else language

    def _normalize(self, language: str | None) -> str:
        if not language or not self.is_supported(language):
            return self._config.default_language
        return language

    def _svc(self, language: str) -> TranslationService:
        lang = self._normalize(language)
        return TranslationService(lang, loader=self._i18n.loader if self._i18n else None)

    def _locale(self, language: str) -> LocaleManager:
        return LocaleManager(self._normalize(language))

    # ── Resolution & change (delegates to i18n persistence) ─────

    async def resolve_current(
        self,
        *,
        query: str | None = None,
        cookie: str | None = None,
        header: str | None = None,
        user_id=None,
        device_id: str | None = None,
    ) -> str:
        """Resolve the current output language for this request."""
        if self._i18n is not None:
            resolved = await self._i18n.resolve(
                query=query, cookie=cookie, header=header,
                user_id=user_id, device_id=device_id,
            )
            return resolved.language
        return self._normalize(query)

    async def change_language(
        self,
        language: str,
        *,
        response=None,
        user_id=None,
        device_id: str | None = None,
    ):
        """Change the output language and persist it (browser + DB + profile).

        Future responses automatically use the new language — the conversation
        does not need to restart.
        """
        if not self.is_supported(language):
            raise UnsupportedLanguageError(
                f"Unsupported language '{language}'. Supported: {self._config.supported_languages}"
            )
        lang = self._normalize(language)
        if self._i18n is not None:
            await self._i18n.switch(
                lang, response=response,
                user_id=user_id, device_id=device_id, source="manual",
            )
        cfg = BUILTIN_LOCALES.get(lang)
        return LanguageChangeResult(
            status="switched",
            language=lang,
            display_name=cfg.display_name if cfg else lang,
            native_name=cfg.native_name if cfg else lang,
            future_responses_use=lang,
        )

    # ── Detection ───────────────────────────────────────────────

    def detect(self, text: str) -> DetectionResult:
        """Detect the language of ``text`` (pure heuristic)."""
        return detect_language(
            text,
            supported=self._config.supported_languages,
            default=self._config.default_language,
        )

    # ── Prompt injection (reasoning stays English) ──────────────

    def build_system_instruction(self, system_prompt: str, language: str) -> str:
        """Return a system prompt that asks for a reply in ``language``.

        The added instruction is written in English; only the *output* is
        required to be in the selected language.
        """
        if not self._config.prompt_inject_language or language == "en":
            return system_prompt
        name = self.language_name(language)
        return (
            f"{system_prompt}\n\n"
            f"Respond to the user in {name}. Keep every ASIN, SKU, product code, "
            f"and numeric value exactly as-is. Do not translate codes or unit "
            f"prices. Reason in English internally, but write the final answer "
            f"only in {name}."
        )

    # ── LLM prose translation ───────────────────────────────────

    async def translate_text(self, text: str, language: str) -> str:
        """Translate free-form prose to ``language``.

        Uses the configured LLM when available and enabled; otherwise returns the
        text unchanged (deterministic fallback preserves codes/numbers exactly).
        """
        lang = self._normalize(language)
        if lang == "en" or not self._config.llm_translate or self._llm is None:
            return text
        name = self.language_name(lang)
        try:
            response = await self._llm.generate_with_retry(
                system_prompt=_TRANSLATE_SYSTEM,
                user_prompt=f"Translate into {name}:\n\n{text}",
            )
            out = (response.content or "").strip()
            return out or text
        except Exception:
            return text

    # ── Assistant-response localization ─────────────────────────

    async def localize_response(
        self, response: AssistantResponse, language: str,
    ) -> AssistantResponse:
        """Localize an assistant response for ``language``.

        - Localizes the capability + confidence display labels and the retrieved
          context summaries (data preserved verbatim).
        - Keeps enum values / API fields English.
        - Optionally translates free-form ``answer`` prose via the LLM when the
          response was not already generated in the target language.
        """
        lang = self._normalize(language)
        t = self._svc(lang)

        answer = response.answer
        # Only translate prose if the provider did not already emit it in-language.
        if lang != "en" and response.provider_used != "fallback":
            answer = await self.translate_text(answer, lang)

        return AssistantResponse(
            answer=answer,
            capability=response.capability,
            confidence=response.confidence,
            contexts=localize_contexts(response.contexts, t) if response.contexts else [],
            model_used=response.model_used,
            provider_used=response.provider_used,
            prompt_version=response.prompt_version,
            latency_ms=response.latency_ms,
            structured_data=response.structured_data,
            language=lang,
            capability_label=localize_capability(response.capability, t),
            confidence_label=localize_confidence(response.confidence, t),
        )

    def localize_labels(
        self, response: AssistantResponse, language: str,
    ) -> AssistantResponse:
        """Localize only the structured labels on a response.

        The ``answer`` text is left untouched (it is expected to already be in
        ``language`` via prompt injection). Used by the assistant engine after the
        LLM produces an in-language answer.
        """
        lang = self._normalize(language)
        t = self._svc(lang)
        return AssistantResponse(
            answer=response.answer,
            capability=response.capability,
            confidence=response.confidence,
            contexts=localize_contexts(response.contexts, t) if response.contexts else [],
            model_used=response.model_used,
            provider_used=response.provider_used,
            prompt_version=response.prompt_version,
            latency_ms=response.latency_ms,
            structured_data=response.structured_data,
            language=lang,
            capability_label=localize_capability(response.capability, t),
            confidence_label=localize_confidence(response.confidence, t),
        )

    def fallback_answer(
        self,
        question: str,
        contexts: list[RetrievedContext],
        language: str,
    ) -> str:
        """Build a deterministic, rule-based answer in ``language``."""
        lang = self._normalize(language)
        svc = self._svc(lang)
        parts = [svc.t("multilingual.content.analysis_for", question=question), ""]
        for c in contexts:
            parts.append(f"• {localize_source_summary(c, svc)}")
        if not contexts:
            parts.append(svc.t("multilingual.content.no_data"))
        parts.append("")
        parts.append(svc.t("multilingual.content.rule_based"))
        return "\n".join(parts)

    # ── Structured content localizers ───────────────────────────

    def localize_table(
        self, *, title_key: str, columns: list[dict[str, Any]],
        rows: list[dict[str, Any]], language: str,
    ) -> LocalizedTable:
        lang = self._normalize(language)
        return localize_table(
            title_key=title_key, columns=columns, rows=rows,
            svc=self._svc(lang), locale=self._locale(lang),
        )

    def localize_chart(
        self, *, title_key: str, x_axis_key: str | None, y_axis_key: str | None,
        labels: list[str], series: list[dict[str, Any]], language: str,
        currency: bool = False,
    ) -> LocalizedChart:
        lang = self._normalize(language)
        return localize_chart(
            title_key=title_key, x_axis_key=x_axis_key, y_axis_key=y_axis_key,
            labels=labels, series=series, svc=self._svc(lang),
            locale=self._locale(lang), currency=currency,
        )

    def localize_recommendation(
        self, *, action: str, entity: str, detail: str, language: str,
        confidence: str | None = None, value: float | None = None,
    ) -> LocalizedRecommendation:
        return localize_recommendation(
            action=action, entity=entity, detail=detail,
            confidence=confidence, value=value, svc=self._svc(language),
        )

    def localize_notification(
        self, *, title: str, body: str, language: str,
        severity: str | None = None, timestamp: str | None = None,
    ) -> LocalizedNotification:
        return localize_notification(
            title=title, body=body, severity=severity, timestamp=timestamp,
            svc=self._svc(language),
        )

    def localize_report(
        self, *, title: str, sections: list[dict[str, Any]], language: str,
        generated: str | None = None,
    ) -> LocalizedReport:
        return localize_report(
            title=title, sections=sections, generated=generated,
            svc=self._svc(language),
        )

    def localize_email(
        self, *, subject: str, body: str, language: str,
    ) -> LocalizedEmail:
        return localize_email(
            subject=subject, body=body, svc=self._svc(language),
        )
