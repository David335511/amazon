"""Prompt template registry — keeps prompts separate from business logic.

Design decisions:
- Prompts are registered by name with version metadata.
- The registry provides a single entry point for all prompt templates.
- New prompts can be added without modifying existing code.
- Prompt versions enable A/B testing and migration.
"""

from __future__ import annotations

from typing import Any

from app.ai.prompts.assistant import (
    ASSISTANT_PROMPTS,
    ASSISTANT_PROMPT_VERSIONS,
    build_assistant_user_prompt,
)
from app.ai.prompts.sourcing import (
    PROMPT_REGISTRY as SOURCING_PROMPTS,
    PROMPT_VERSIONS as SOURCING_VERSIONS,
    build_sourcing_user_prompt,
)

# Merge all prompt registries
PROMPT_REGISTRY: dict[str, tuple[str, str]] = {}
PROMPT_REGISTRY.update(SOURCING_PROMPTS)
PROMPT_REGISTRY.update(ASSISTANT_PROMPTS)

PROMPT_VERSIONS: dict[str, str] = {}
PROMPT_VERSIONS.update(SOURCING_VERSIONS)
PROMPT_VERSIONS.update(ASSISTANT_PROMPT_VERSIONS)

__all__ = [
    "get_prompt",
    "list_prompts",
    "PROMPT_REGISTRY",
    "PROMPT_VERSIONS",
]


def get_prompt(
    prompt_name: str,
    data: dict[str, Any],
) -> tuple[str, str] | None:
    """Get a system prompt and build a user prompt from data.

    Args:
        prompt_name: Name of the prompt template (e.g., 'sourcing_analysis_v1').
        data: Data to interpolate into the user prompt.

    Returns:
        Tuple of (system_prompt, user_prompt) or None if not found.
    """
    if prompt_name not in PROMPT_REGISTRY:
        return None

    system_prompt, builder_func_name = PROMPT_REGISTRY[prompt_name]

    # Dynamically call the builder function
    if builder_func_name == "build_sourcing_user_prompt":
        user_prompt = build_sourcing_user_prompt(data)
    elif builder_func_name == "build_assistant_user_prompt":
        question = data.get("question", "")
        capability = data.get("capability", "general_query")
        contexts = data.get("contexts", [])
        user_prompt = build_assistant_user_prompt(question, capability, contexts)
    else:
        user_prompt = str(data)

    return system_prompt, user_prompt


def list_prompts() -> list[dict[str, str]]:
    """List all registered prompts with metadata."""
    return [
        {
            "name": name,
            "version": PROMPT_VERSIONS.get(name, "0.0.0"),
        }
        for name in PROMPT_REGISTRY
    ]
