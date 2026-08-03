"""LanguageSwitcher — resolves, switches and persists the active language.

This is the single object that implements the persistence contract:

- **browser** — sets/reads the language cookie on the HTTP response/request.
- **database** — upserts a row in ``i18n_language_preferences`` per
  (user, device).
- **user profile** — writes the language into ``UserSettings.display_preferences``.
- **API requests** — resolution honours ``?lang=``, the ``lang`` cookie, the
  ``Accept-Language`` header and the stored database preference.

Resolution priority (highest first):

    query param > cookie > Accept-Language header > stored preference > default

Only *displayed* content is translated; system logs, DB field names and API
field names always stay in English.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Response
from sqlalchemy import select

from app.core.logging import get_logger
from app.i18n.config import I18nConfig
from app.i18n.errors import LanguageUnsupportedError
from app.i18n.repository import I18nRepository

logger = get_logger(__name__)

_LANGUAGE_FIELD = "language"
_PROFILE_KEY = "i18n"


@dataclass
class ResolvedLanguage:
    """The language selected for a request plus its provenance."""

    language: str
    source: str


class LanguageSwitcher:
    """Resolves and persists the selected language across all backends."""

    def __init__(
        self,
        repository: I18nRepository,
        config: I18nConfig | None = None,
        session=None,
    ) -> None:
        self._repo = repository
        self._config = config or I18nConfig()
        # The DB session is needed to touch UserSettings (user-profile persistence).
        self._session = session

    # ── Resolution ────────────────────────────────────────────────────────

    def supported(self) -> list[str]:
        return list(self._config.supported_languages)

    def is_supported(self, language: str | None) -> bool:
        return bool(language) and language in self._config.supported_languages

    def normalize(self, language: str | None) -> str:
        """Return a supported language, falling back to the default."""
        if self.is_supported(language):
            return language  # type: ignore[return-value]
        return self._config.default_language

    async def resolve(
        self,
        *,
        query: str | None = None,
        cookie: str | None = None,
        header: str | None = None,
        user_id: str | uuid.UUID | None = None,
        device_id: str | None = None,
    ) -> ResolvedLanguage:
        """Resolve the active language from request signals + stored preference."""
        for candidate, source in (
            (query, "query"),
            (cookie, "cookie"),
            (header, "header"),
        ):
            if self.is_supported(candidate):
                return ResolvedLanguage(language=candidate, source=source)

        # No explicit request signal — consult the stored preference.
        stored = await self.get_preference(user_id=user_id, device_id=device_id)
        if stored and self.is_supported(stored.get("language")):
            return ResolvedLanguage(language=stored["language"], source=stored.get("source") or "profile")

        return ResolvedLanguage(language=self._config.default_language, source="default")

    # ── Switching ─────────────────────────────────────────────────────────

    async def switch(
        self,
        language: str,
        *,
        response: Response | None = None,
        user_id: str | uuid.UUID | None = None,
        device_id: str | None = None,
        source: str = "manual",
        persist_to_db: bool | None = None,
        persist_to_profile: bool | None = None,
    ) -> dict[str, bool]:
        """Switch to a language and persist it to every configured backend.

        Returns a ``{backend: bool}`` map describing what was persisted.
        """
        if not self.is_supported(language):
            raise LanguageUnsupportedError(
                f"Unsupported language '{language}'. Supported: {self.supported()}"
            )

        persisted: dict[str, bool] = {}

        # 1) Browser cookie.
        if response is not None:
            response.set_cookie(
                key=self._config.cookie_name,
                value=language,
                max_age=self._config.cookie_max_age,
                httponly=self._config.cookie_httponly,
                samesite=self._config.cookie_samesite,
            )
            persisted["browser"] = True

        # 2) Database preference.
        want_db = self._config.persist_to_db if persist_to_db is None else persist_to_db
        if want_db and (user_id or device_id):
            try:
                await self._repo.upsert(
                    language=language, source=source,
                    user_id=user_id, device_id=device_id,
                )
                persisted["database"] = True
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning("Failed to persist language preference to DB: %s", exc)
                persisted["database"] = False

        # 3) User profile (UserSettings.display_preferences).
        want_profile = (
            self._config.persist_to_user_profile if persist_to_profile is None else persist_to_profile
        )
        if want_profile and user_id:
            persisted["profile"] = await self._persist_to_profile(user_id, language)

        return persisted

    async def _persist_to_profile(self, user_id: str | uuid.UUID, language: str) -> bool:
        """Write the language into the user's settings profile (best-effort)."""
        if self._session is None:  # pragma: no cover - not wired with a session
            return False
        try:
            from app.domain.models.sourcing import UserSettings

            uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
            result = await self._session.execute(
                select(UserSettings).where(UserSettings.user_id == uid)
            )
            settings_row = result.scalars().first()
            if settings_row is None:
                return False
            prefs = dict(settings_row.display_preferences or {})
            profile = dict(prefs.get(_PROFILE_KEY) or {})
            profile[_LANGUAGE_FIELD] = language
            prefs[_PROFILE_KEY] = profile
            settings_row.display_preferences = prefs
            await self._session.flush()
            return True
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("Failed to persist language to user profile: %s", exc)
            return False

    async def _profile_language(self, user_id: str | uuid.UUID) -> str | None:
        """Read the language stored in the user's settings profile."""
        if self._session is None:  # pragma: no cover
            return None
        try:
            from app.domain.models.sourcing import UserSettings

            uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
            result = await self._session.execute(
                select(UserSettings).where(UserSettings.user_id == uid)
            )
            row = result.scalars().first()
            if row is None:
                return None
            profile = dict(row.display_preferences or {}).get(_PROFILE_KEY) or {}
            return profile.get(_LANGUAGE_FIELD)
        except Exception:  # pragma: no cover - best-effort
            return None

    # ── Preference access ─────────────────────────────────────────────────

    async def get_preference(
        self,
        *,
        user_id: str | uuid.UUID | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the stored preference for a (user, device) key, or None."""
        row = await self._repo.get_preference(user_id=user_id, device_id=device_id)
        if row is not None:
            return {
                "user_id": str(row.user_id) if row.user_id else None,
                "device_id": row.device_id,
                "language": row.language,
                "source": row.source,
            }
        # Fall back to the user profile when no DB row exists.
        if user_id:
            lang = await self._profile_language(user_id)
            if lang:
                return {"user_id": str(user_id), "device_id": None,
                        "language": lang, "source": "profile"}
        return None


def dumps_preferences(prefs: dict[str, Any]) -> str:
    """Serialize display preferences for storage."""
    return json.dumps(prefs, ensure_ascii=False, default=str)
