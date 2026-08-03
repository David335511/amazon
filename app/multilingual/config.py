"""Multilingual AI support — config.

Controls the set of supported output languages, how the AI assistant selects the
response language, the language-detection thresholds, and the LLM-translation
behaviour. All prompts and AI reasoning stay English internally; only the final
user-facing output is produced in the selected language.
"""

from __future__ import annotations

from pydantic import BaseModel


class MultilingualConfig(BaseModel):
    """Configuration for multilingual AI responses.

    - ``supported_languages`` is the whitelist of output languages.
    - ``prompt_inject_language`` appends an English instruction telling the LLM to
      write its final answer in the selected language (reasoning stays English).
    - ``llm_translate`` enables an optional LLM pass to translate free-form prose
      when the assistant was not already prompted to reply in the target language.
    - ``llm_translate_fallback`` falls back to a deterministic localizer when no
      LLM is configured (structured labels always localize; prose is preserved).
    """

    enabled: bool = True
    default_language: str = "en"
    supported_languages: list[str] = ["en", "zh-CN"]

    # Language detection (pure heuristic over Unicode ranges).
    detect_min_cjk_ratio: float = 0.5
    detect_min_latin_ratio: float = 0.5

    # Prompt / translation behaviour.
    prompt_inject_language: bool = True
    llm_translate: bool = True
    llm_translate_fallback: bool = True

    @property
    def as_snapshot(self) -> dict:
        return self.model_dump()
