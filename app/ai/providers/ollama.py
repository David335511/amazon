"""Ollama provider — uses Ollama's local API for running models locally.

No API key required. Configured via: OLLAMA_BASE_URL or OLLAMA_HOST environment variable.
Default: http://localhost:11434
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from app.ai.base import LLMConfig, LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    """LLM provider using Ollama's local API.

    Runs models locally (Llama 3, Mistral, Gemma, etc.).
    No API key needed — just a running Ollama instance.
    """

    provider_name = "ollama"

    def __init__(
        self,
        config: LLMConfig | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(config)
        self._base_url = (
            base_url
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        )
        # Default model for Ollama
        if config and config.model == "gpt-4o":
            config.model = "llama3.2"

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        cfg = config or self._config
        start = time.monotonic()

        url = f"{self._base_url.rstrip('/')}/api/chat"

        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": cfg.temperature,
                "num_predict": cfg.max_tokens,
                "top_p": cfg.top_p,
            },
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        latency = (time.monotonic() - start) * 1000

        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            model=data.get("model", cfg.model),
            provider=self.provider_name,
            usage={
                "prompt_eval_count": data.get("prompt_eval_count", 0),
                "eval_count": data.get("eval_count", 0),
            },
            finish_reason=data.get("done_reason", "stop"),
            latency_ms=round(latency, 2),
        )

    async def is_available(self) -> bool:
        try:
            url = f"{self._base_url.rstrip('/')}/api/tags"
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
                return response.status_code == 200
        except Exception:
            return False
