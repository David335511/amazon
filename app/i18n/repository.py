"""Persistence layer for the internationalization system.

Stores and retrieves the selected language per (user, device) in the
``i18n_language_preferences`` table. ``upsert`` is an in-place update so
repeated switches never violate the (user, device) unique constraint.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.i18n.models import LanguagePreference
from app.infrastructure.repositories.base import BaseRepository


def _to_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Coerce a string/None id to a UUID (SQLAlchemy Uuid columns need UUIDs)."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


class I18nRepository(BaseRepository[LanguagePreference]):
    """Repository for language preferences."""

    def __init__(self, session) -> None:
        super().__init__(session, LanguagePreference)

    async def get_preference(
        self, *, user_id: str | uuid.UUID | None = None, device_id: str | None = None
    ) -> LanguagePreference | None:
        """Fetch the stored preference for a (user, device) key.

        Requires at least one of user_id / device_id. Prefers the user-scoped
        row, then the device-scoped row.
        """
        uid = _to_uuid(user_id)
        if uid is not None:
            result = await self._session.execute(
                select(LanguagePreference).where(LanguagePreference.user_id == uid)
            )
            row = result.scalars().first()
            if row is not None:
                return row
        if device_id:
            result = await self._session.execute(
                select(LanguagePreference)
                .where(LanguagePreference.device_id == device_id)
                .order_by(LanguagePreference.updated_at.desc())
            )
            return result.scalars().first()
        return None

    async def upsert(
        self,
        *,
        language: str,
        source: str,
        user_id: str | uuid.UUID | None = None,
        device_id: str | None = None,
    ) -> LanguagePreference | None:
        """Create or update the (user, device) preference in place.

        Returns None when there is no key to persist (both user_id and device_id
        are None) or the user_id cannot be coerced to a UUID.
        """
        uid = _to_uuid(user_id)
        if uid is None and not device_id:
            return None

        existing: LanguagePreference | None = None
        if uid is not None:
            result = await self._session.execute(
                select(LanguagePreference).where(LanguagePreference.user_id == uid)
            )
            existing = result.scalars().first()
        if existing is None and device_id:
            result = await self._session.execute(
                select(LanguagePreference)
                .where(LanguagePreference.device_id == device_id)
                .order_by(LanguagePreference.updated_at.desc())
            )
            existing = result.scalars().first()

        if existing is not None:
            existing.language = language
            existing.source = source
            if uid is not None:
                existing.user_id = uid
            if device_id:
                existing.device_id = device_id
            await self._session.flush()
            await self._session.refresh(existing)
            return existing

        row = LanguagePreference(
            user_id=uid, device_id=device_id, language=language, source=source,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list_all(self, limit: int = 100) -> list[LanguagePreference]:
        result = await self._session.execute(
            select(LanguagePreference).order_by(LanguagePreference.updated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self._session.execute(select(LanguagePreference.id))
        return len(result.all())


def _dump(row: LanguagePreference | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "user_id": str(row.user_id) if row.user_id else None,
        "device_id": row.device_id,
        "language": row.language,
        "source": row.source,
    }
