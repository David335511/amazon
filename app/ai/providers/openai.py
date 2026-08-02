"""OpenAI provider — uses the openai Python SDK.

Requires: pip install openai
Configured via: OPENAI_API_KEY environment variable.
"""

from __future__ import annotations

import os
import time
from typing import Any

from app.ai.base import LLMConfig, LLMProvider, LLMResponse


class OpenAIClientProvider(LLMProvider):
    """LLM provider using the OpenAI Python SDK.

    Supports GPT-4o, GPT-4, GPT-3.5-turbo, and any OpenAI-compatible API.
    Can be used with Azure OpenAI, Together AI, or any OpenAI-compatible endpoint
    by setting the `api_base` extra parameter.
    """

    provider_name = "openai"

    def __init__(
        self,
        config: LLMConfig | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        super().__init__(config)
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._api_base = api_base or config.extra.get("api_base") if config else None

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        cfg = config or self._config
        start = time.monotonic()

        try:
            from openai import AsyncOpenAI

            client_kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._api_base:
                client_kwargs["base_url"] = self._api_base

            client = AsyncOpenAI(**client_kwargs)

            response = await client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                top_p=cfg.top_p,
                frequency_penalty=cfg.frequency_penalty,
                presence_penalty=cfg.presence_penalty,
                timeout=cfg.timeout_seconds,
            )

            latency = (time.monotonic() - start) * 1000
            choice = response.choices[0] if response.choices else None

            return LLMResponse(
                content=choice.message.content or "" if choice else "",
                model=response.model,
                provider=self.provider_name,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                } if response.usage else None,
                finish_reason=choice.finish_reason if choice else None,
                latency_ms=round(latency, 2),
            )
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI SDK not installed. Run: pip install openai"
            ) from exc

    async def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self._api_key)
            await client.models.list()
            return True
        except Exception:
            return False
