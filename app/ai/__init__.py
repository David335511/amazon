"""AI reasoning module — LLM-powered product analysis with provider abstraction.

Design decisions:
- Abstract `LLMProvider` interface allows swapping providers (OpenAI, Anthropic, Ollama).
- Prompt templates are kept in `app/ai/prompts/` — separate from business logic.
- The `AIReasoningEngine` orchestrates provider calls and parses structured output.
- All providers return the same `AIRecommendation` model — no provider-specific types.
- Providers are configured via environment variables with sensible defaults.
- Graceful degradation: if no provider is configured, falls back to rule-based reasoning.
"""

from app.ai.base import LLMProvider, LLMConfig, LLMResponse
from app.ai.reasoning import AIReasoningEngine, AIRecommendation, RecommendationAction
from app.ai.providers import (
    AnthropicProvider,
    OllamaProvider,
    OpenAIClientProvider,
    create_provider,
)

__all__ = [
    "LLMProvider",
    "LLMConfig",
    "LLMResponse",
    "AIReasoningEngine",
    "AIRecommendation",
    "RecommendationAction",
    "AnthropicProvider",
    "OllamaProvider",
    "OpenAIClientProvider",
    "create_provider",
]
