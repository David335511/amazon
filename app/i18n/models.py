"""ORM models for the internationalization system.

A single table:

- ``i18n_language_preferences`` — one row per (user, device) storing the
  selected language so it persists across browsers, devices and sessions.
  ``user_id`` ties the preference to a user profile; ``device_id`` ties it to a
  specific browser/device when the user is anonymous. At least one key must be
  set. The row is upserted whenever a user switches language.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base, TimestampMixin, UUIDMixin


class LanguageSource(StrEnum):
    """How the preference was selected."""

    MANUAL = "manual"
    API = "api"
    COOKIE = "cookie"
    PROFILE = "profile"


class LanguagePreference(Base, UUIDMixin, TimestampMixin):
    """Stores the language a user/device selected."""

    __tablename__ = "i18n_language_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "device_id", name="uq_i18n_pref_user_device",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Owner user profile (nullable for anonymous/device preferences)",
    )
    device_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
        comment="Browser/device identifier when the user is anonymous",
    )
    language: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="Selected language code (e.g. en, zh-CN)",
    )
    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=LanguageSource.MANUAL.value,
        comment="LanguageSource (manual | api | cookie | profile)",
    )

    def __repr__(self) -> str:
        return f"<LanguagePreference(user={self.user_id}, device={self.device_id}, lang={self.language})>"
