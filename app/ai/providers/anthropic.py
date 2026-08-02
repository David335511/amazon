"""Anthropic provider — uses the anthropic Python SDK (Claude).

Requires: pip install anthropic
Configured via: ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import os
import time
from typing import Any

from app.ai.base import LLMConfig, LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    """LLM provider using the Anthropic Python SDK.

    Supports Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku,
    and any Anthropic model available via the API.
    """

    provider_name = "anthropic"

    def __init__(
        self,
        config: LLMConfig | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        super().__init__(config)
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
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
            from anthropic import AsyncAnthropic

            client_kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._api_base:
                client_kwargs["base_url"] = self._api_base

            client = AsyncAnthropic(**client_kwargs)

            response = await client.messages.create(
                model=cfg.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                top_p=cfg.top_p,
                timeout=cfg.timeout_seconds,
            )

            latency = (time.monotonic() - start) * 1000

            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text

            return LLMResponse(
                content=content,
                model=response.model,
                provider=self.provider_name,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                } if response.usage else None,
                finish_reason=response.stop_reason,
                latency_ms=round(latency, 2),
            )
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic SDK not installed. Run: pip install anthropic"
            ) from exc

    async def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self._api_key)
            await client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False
