"""Multilingual AI support for the Amazon AI Commerce Platform.

Design decisions:
- The AI assistant responds in the user's selected language (en / zh-CN).
- AI reasoning stays language-independent; prompts remain English internally.
- Only the final user-facing output is produced in the selected language.
- Charts, tables, recommendations, notifications, reports and emails are
  localized deterministically via the i18n translation service + locale
  formatters (works with no LLM configured).
- Switching language does not restart the conversation; future responses
  automatically use the new language (persisted to browser + DB + profile).
- Only user-facing text is translated; DB fields, API field names, configuration,
  code, logs, SQL and JSON keys stay English.
"""

from app.multilingual.config import MultilingualConfig
from app.multilingual.detection import DetectionResult, detect_language
from app.multilingual.errors import (
    LanguageDetectionError,
    MultilingualError,
    UnsupportedLanguageError,
)
from app.multilingual.manager import MultilingualManager
from app.multilingual.schemas import (
    DetectRequest,
    LanguageChangeResult,
    LocalizedChart,
    LocalizedEmail,
    LocalizedNotification,
    LocalizedRecommendation,
    LocalizedReport,
    LocalizedTable,
    MultilingualCapabilities,
)

__all__ = [
    "DetectRequest",
    "DetectionResult",
    "LanguageChangeResult",
    "LanguageDetectionError",
    "LocalizedChart",
    "LocalizedEmail",
    "LocalizedNotification",
    "LocalizedRecommendation",
    "LocalizedReport",
    "LocalizedTable",
    "MultilingualCapabilities",
    "MultilingualConfig",
    "MultilingualError",
    "MultilingualManager",
    "UnsupportedLanguageError",
    "detect_language",
]
