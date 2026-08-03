"""Multilingual AI API — language detection, switching and response localization.

Endpoints:
- GET   /multilingual/capabilities    — supported output languages + behaviour
- GET   /multilingual/languages       — list available output languages
- GET   /multilingual/current         — resolve the current output language
- POST  /multilingual/language        — change the output language (persists)
- POST  /multilingual/detect          — detect the language of a text
- POST  /multilingual/translate       — translate free-form prose
- POST  /multilingual/localize/response      — localize an assistant response
- POST  /multilingual/localize/table         — localize a table
- POST  /multilingual/localize/chart         — localize a chart
- POST  /multilingual/localize/recommendation— localize a recommendation
- POST  /multilingual/localize/notification  — localize a notification
- POST  /multilingual/localize/report        — localize a report
- POST  /multilingual/localize/email         — localize an email
"""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from app.core.dependencies import get_multilingual_manager
from app.multilingual.manager import MultilingualManager
from app.multilingual.schemas import (
    DetectRequest,
    LanguageChangeResult,
    LocalizeAssistantRequest,
    LocalizeChartRequest,
    LocalizedChart,
    LocalizedEmail,
    LocalizedNotification,
    LocalizedRecommendation,
    LocalizedReport,
    LocalizedTable,
    LocalizeEmailRequest,
    LocalizeNotificationRequest,
    LocalizeRecommendationRequest,
    LocalizeReportRequest,
    LocalizeTableRequest,
    MultilingualCapabilities,
)

router = APIRouter(prefix="/multilingual", tags=["multilingual"])

ManagerDep = Annotated[MultilingualManager, Depends(get_multilingual_manager)]


@router.get("/capabilities", response_model=MultilingualCapabilities)
async def capabilities(manager: ManagerDep) -> MultilingualCapabilities:
    """Supported output languages and multilingual-AI behaviour."""
    return manager.capabilities()


@router.get("/languages")
async def list_languages(manager: ManagerDep):
    """List the languages the assistant can respond in."""
    return manager.available_languages()


@router.get("/current")
async def current_language(
    manager: ManagerDep,
    request: Request,
    lang_cookie: str | None = Cookie(default=None, alias="lang"),
    accept_language: str | None = Header(default=None),
) -> dict:
    """Resolve the current output language for this request.

    Priority: query param (?lang=) > lang cookie > Accept-Language > stored
    preference > default.
    """
    query = request.query_params.get("lang")
    language = await manager.resolve_current(
        query=query,
        cookie=lang_cookie,
        header=_parse_accept_language(accept_language),
        user_id=request.query_params.get("user_id"),
        device_id=request.headers.get("X-Device-Id"),
    )
    return {
        "language": language,
        "native_name": manager.language_name(language),
        "future_responses_use": language,
    }


@router.post("/language", response_model=LanguageChangeResult)
async def change_language(
    manager: ManagerDep,
    request: Request,
    response: Response,
    language: str = Query(..., description="Language code (e.g. 'en', 'zh-CN')"),
    user_id: str | None = Query(default=None),
) -> LanguageChangeResult:
    """Change the assistant's output language.

    Persists to the browser cookie, the database preference and the user profile,
    so all future responses automatically use the new language — the current
    conversation continues without restarting.
    """
    try:
        return await manager.change_language(
            language,
            response=response,
            user_id=user_id,
            device_id=request.headers.get("X-Device-Id"),
        )
    except Exception as exc:  # UnsupportedLanguageError etc.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc


@router.post("/detect")
async def detect(manager: ManagerDep, payload: DetectRequest) -> dict:
    """Detect the language of a text (pure heuristic, offline)."""
    result = manager.detect(payload.text)
    return {
        "detected_language": result.detected_language,
        "confidence": result.confidence,
        "script": result.script,
        "supported": result.supported,
        "sample_text": result.sample_text,
    }


@router.post("/translate")
async def translate(
    manager: ManagerDep,
    language: str = Query(...),
    text: str = Query(..., max_length=8000),
) -> dict:
    """Translate free-form prose to the selected language."""
    out = await manager.translate_text(text, language)
    return {"language": manager.normalize(language), "translated": out}


# ── Response & structured-content localization ───────────────


@router.post("/localize/response")
async def localize_response(
    manager: ManagerDep, payload: LocalizeAssistantRequest,
):
    """Localize an assistant response for a language."""
    result = await manager.localize_response(
        payload.response, payload.language or "en",
    )
    return result


@router.post("/localize/table", response_model=LocalizedTable)
async def localize_table(
    manager: ManagerDep, payload: LocalizeTableRequest,
) -> LocalizedTable:
    return manager.localize_table(
        title_key=payload.title_key,
        columns=[c.model_dump() for c in payload.columns],
        rows=payload.rows,
        language=payload.language or "en",
    )


@router.post("/localize/chart", response_model=LocalizedChart)
async def localize_chart(
    manager: ManagerDep, payload: LocalizeChartRequest,
) -> LocalizedChart:
    return manager.localize_chart(
        title_key=payload.title_key,
        x_axis_key=payload.x_axis_key,
        y_axis_key=payload.y_axis_key,
        labels=payload.labels,
        series=[s.model_dump() for s in payload.series],
        language=payload.language or "en",
        currency=payload.currency,
    )


@router.post("/localize/recommendation", response_model=LocalizedRecommendation)
async def localize_recommendation(
    manager: ManagerDep, payload: LocalizeRecommendationRequest,
) -> LocalizedRecommendation:
    return manager.localize_recommendation(
        action=payload.action, entity=payload.entity, detail=payload.detail,
        confidence=payload.confidence, value=payload.value,
        language=payload.language or "en",
    )


@router.post("/localize/notification", response_model=LocalizedNotification)
async def localize_notification(
    manager: ManagerDep, payload: LocalizeNotificationRequest,
) -> LocalizedNotification:
    return manager.localize_notification(
        title=payload.title, body=payload.body,
        severity=payload.severity, timestamp=payload.timestamp,
        language=payload.language or "en",
    )


@router.post("/localize/report", response_model=LocalizedReport)
async def localize_report(
    manager: ManagerDep, payload: LocalizeReportRequest,
) -> LocalizedReport:
    return manager.localize_report(
        title=payload.title, sections=payload.sections,
        generated=payload.generated, language=payload.language or "en",
    )


@router.post("/localize/email", response_model=LocalizedEmail)
async def localize_email(
    manager: ManagerDep, payload: LocalizeEmailRequest,
) -> LocalizedEmail:
    return manager.localize_email(
        subject=payload.subject, body=payload.body, language=payload.language or "en",
    )


def _parse_accept_language(header: str | None) -> str | None:
    if not header:
        return None
    return header.split(",")[0].split(";")[0].strip()
