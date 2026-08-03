"""Configuration for the experimentation platform.

Everything about how experiments are run — significance threshold, minimum
sample size, default RNG seed (for reproducible assignment), variant limits and
the deploy's code version (recorded on every experiment start for
reproducibility) — is governed here. Follows the layered-config convention:
Pydantic defaults overridable via YAML (``config/<env>.yaml`` -> ``experiments:``
block) and environment variables.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ExperimentConfig(BaseSettings):
    """Runtime settings for the experimentation platform."""

    enabled: bool = True

    # ── Statistical defaults ──────────────────────────────────────────────
    default_alpha: float = 0.05            # significance threshold (two-sided)
    default_min_sample_size: int = 100     # observations per variant required
    default_seed: int = 42                 # reproducible variant assignment

    # ── Guardrails ────────────────────────────────────────────────────────
    max_variants_per_experiment: int = 20  # hard cap on variants per experiment
    max_batch_size: int = 1000             # max observations per record batch

    # ── Reproducibility ───────────────────────────────────────────────────
    # Commit / build the deployment was created from. Snapshot onto every
    # experiment at start so a report can always be traced back to the exact
    # code that produced it. Set via env var CODE_VERSION (e.g. a git short SHA).
    code_version: str = ""

    model_config = SettingsConfigDict(extra="ignore")
