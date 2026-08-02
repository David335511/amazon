"""Abstract LLM provider interface — supports OpenAI, Anthropic, Ollama, and future providers.

Design decisions:
- ABC enforces that all providers implement the same `generate()` method.
- `LLMConfig` holds provider-agnostic settings (model, temperature, max_tokens).
- `LLMResponse` is the universal return type — no provider-specific types leak.
- Providers are stateless — configuration is passed at construction time.
- Streaming is supported via the `stream` parameter for real-time applications.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMConfig:
    """Provider-agnostic LLM configuration.

    Each provider maps these to its own specific parameters.
    """

    model: str = "gpt-4o"
    temperature: float = 0.3
    max_tokens: int = 2048
    top_p: float = 0.95
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout_seconds: int = 60
    max_retries: int = 3
    retry_base_delay: float = 1.0

    # Provider-specific overrides (e.g., {"api_base": "..."})
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Universal response from any LLM provider."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] | None = None
    finish_reason: str | None = None
    latency_ms: float = 0.0


class LLMProvider(ABC):
    """Abstract base class that all LLM providers must implement.

    Usage:
        provider = OpenAIClientProvider(api_key="...")
        response = await provider.generate(
            system_prompt="You are a sourcing analyst.",
            user_prompt="Analyze this product...",
        )
        print(response.content)
    """

    provider_name: str = ""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._config = config or LLMConfig()

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            system_prompt: System-level instructions for the model.
            user_prompt: The user's request/message.
            config: Optional per-call config override.

        Returns:
            LLMResponse with the generated content.
        """

    async def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Generate with automatic retry on failure.

        Uses exponential backoff up to max_retries attempts.
        """
        import asyncio

        cfg = config or self._config
        last_error: Exception | None = None

        for attempt in range(cfg.max_retries):
            try:
                return await self.generate(system_prompt, user_prompt, config=config)
            except Exception as exc:
                last_error = exc
                if attempt < cfg.max_retries - 1:
                    delay = cfg.retry_base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"LLM generation failed after {cfg.max_retries} retries: {last_error}",
        ) from last_error

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is configured and available.

        Returns:
            True if the provider can be used, False otherwise.
        """
