"""Configuration for the multi-agent orchestration framework.

Layered-config convention shared by the other subsystems: Pydantic defaults,
overridable via YAML (``config/<env>.yaml`` -> ``multiagent:`` block) and
environment variables. The DI layer validates the raw YAML block into a
`MultiAgentConfig`.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MultiAgentConfig(BaseSettings):
    """Runtime settings for the multi-agent framework."""

    enabled: bool = True

    # Default set of agents to run for a pipeline, in a natural order. The
    # supervisor still executes them as a dependency DAG (parallel waves), so
    # order here is advisory only (planner/supervision is always run first).
    default_pipeline_roles: list[str] = Field(
        default_factory=lambda: [
            "planner",
            "research",
            "matching",
            "forecast",
            "pricing",
            "profit",
            "risk",
            "negotiation",
            "inventory",
            "reporting",
        ]
    )

    # Cap on how many agents may run concurrently in one wave.
    max_parallel_agents: int = 10

    # Cap on nested delegations any single agent may issue.
    max_delegations_per_agent: int = 10

    # Persist the pipeline shared-memory snapshot with the run record.
    store_shared_memory: bool = True

    model_config = SettingsConfigDict(extra="ignore")
