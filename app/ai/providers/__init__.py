"""LLM provider implementations — OpenAI, Anthropic, Ollama.

Design decisions:
- Each provider is a separate module for clean dependency management.
- Providers are auto-discovered by the `create_provider()` factory.
- API keys are read from environment variables with clear names.
- All providers implement the same `LLMProvider` interface.
"""

from __future__ import annotations

from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.ollama import OllamaProvider
from app.ai.providers.openai import OpenAIClientProvider

__all__ = [
    "AnthropicProvider",
    "OllamaProvider",
    "OpenAIClientProvider",
]


def create_provider(
    provider_type: str | None = None,
    **kwargs: object,
) -> LLMProvider | None:
    """Factory function to create an LLM provider by type.

    Auto-detects the best available provider if none specified:
    1. ANTHROPIC_API_KEY → Anthropic (Claude)
    2. OPENAI_API_KEY → OpenAI (GPT-4o)
    3. OLLAMA_BASE_URL → Ollama (local)

    Args:
        provider_type: One of 'anthropic', 'openai', 'ollama', or None for auto-detect.
        **kwargs: Provider-specific configuration passed to the constructor.

    Returns:
        An LLMProvider instance, or None if no provider is available.
    """
    from app.ai.base import LLMConfig, LLMProvider
    import os

    if provider_type is not None:
        provider_type = provider_type.lower()

    # Auto-detect if no type specified
    if provider_type is None:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider_type = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            provider_type = "openai"
        elif os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST"):
            provider_type = "ollama"
        else:
            return None

    config = LLMConfig(**{k: v for k, v in kwargs.items() if k in LLMConfig.__dataclass_fields__})  # type: ignore[arg-type]
    extra = {k: v for k, v in kwargs.items() if k not in LLMConfig.__dataclass_fields__}

    if provider_type == "anthropic":
        return AnthropicProvider(config=config, **extra)
    if provider_type == "openai":
        return OpenAIClientProvider(config=config, **extra)
    if provider_type == "ollama":
        return OllamaProvider(config=config, **extra)

    raise ValueError(f"Unknown provider type: {provider_type}. Expected: anthropic, openai, ollama")
