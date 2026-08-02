"""Sourcing engine API routes — evaluate products, get rankings, view methodology.

Design decisions:
- Thin route handlers that delegate to the SourcingEngine.
- Accepts product IDs or ASINs for evaluation.
- Returns ranked results with full scoring breakdown.
- Methodology endpoint for transparency.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.repository import AnalyticsRepository
from app.core.database import get_db
from app.core.logging import get_logger
from app.sourcing.engine import SourcingEngine
from app.sourcing.models import (
    ProductEvaluation,
    SourcingConfig,
    SourcingResult,
    SourcingWeights,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/sourcing", tags=["sourcing"])


# ── Dependency ──────────────────────────────────────────────


async def get_sourcing_engine(
    db: AsyncSession = Depends(get_db),
) -> SourcingEngine:
    """Create a SourcingEngine with all dependencies."""
    repository = AnalyticsRepository(db)
    return SourcingEngine(repository=repository)


# ═══════════════════════════════════════════════════════════════
# Evaluation Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/evaluate",
    response_model=SourcingResult,
    summary="Evaluate products for sourcing opportunity",
    description=(
        "Evaluates one or more products against all sourcing rules "
        "and returns ranked results with opportunity scores, confidence, "
        "risk levels, and detailed reasoning."
    ),
)
async def evaluate_products(
    product_ids: list[UUID] = Query(
        ..., description="Product UUIDs to evaluate",
    ),
    days: int = Query(
        default=90, ge=30, le=365,
        description="Analysis window in days for historical data",
    ),
    engine: SourcingEngine = Depends(get_sourcing_engine),
) -> SourcingResult:
    """Evaluate multiple products and return ranked results."""
    if len(product_ids) > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Maximum 100 products per request",
        )

    return await engine.evaluate_products(product_ids, days=days)


@router.get(
    "/evaluate/{product_id}",
    response_model=ProductEvaluation,
    summary="Evaluate a single product",
    description=(
        "Evaluates a single product against all sourcing rules "
        "and returns the full evaluation with scoring breakdown."
    ),
)
async def evaluate_product(
    product_id: UUID,
    days: int = Query(
        default=90, ge=30, le=365,
        description="Analysis window in days",
    ),
    engine: SourcingEngine = Depends(get_sourcing_engine),
) -> ProductEvaluation:
    """Evaluate a single product."""
    evaluation = await engine.evaluate_product(product_id, days=days)
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found or evaluation failed",
        )
    return evaluation


# ═══════════════════════════════════════════════════════════════
# Configuration Endpoints
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/config",
    response_model=SourcingConfig,
    summary="Get default sourcing configuration",
    description="Returns the default sourcing configuration with all thresholds and weights.",
)
async def get_default_config() -> SourcingConfig:
    """Get the default sourcing configuration."""
    return SourcingConfig()


@router.post(
    "/evaluate/custom",
    response_model=SourcingResult,
    summary="Evaluate with custom configuration",
    description=(
        "Evaluate products with a custom sourcing configuration. "
        "Allows overriding default thresholds and weights."
    ),
)
async def evaluate_with_custom_config(
    product_ids: list[UUID] = Query(
        ..., description="Product UUIDs to evaluate",
    ),
    days: int = Query(
        default=90, ge=30, le=365,
        description="Analysis window in days",
    ),
    config: SourcingConfig | None = None,
    engine: SourcingEngine = Depends(get_sourcing_engine),
) -> SourcingResult:
    """Evaluate products with a custom configuration."""
    if len(product_ids) > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Maximum 100 products per request",
        )

    # Create engine with custom config
    custom_engine = SourcingEngine(
        repository=engine._repo,
        config=config or SourcingConfig(),
    )
    return await custom_engine.evaluate_products(product_ids, days=days)


# ═══════════════════════════════════════════════════════════════
# Methodology Endpoint
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/methodology",
    summary="Get scoring methodology documentation",
    description="Returns the complete scoring methodology documentation.",
)
async def get_methodology() -> dict[str, Any]:
    """Get the scoring methodology documentation."""
    return {
        "version": "1.0.0",
        "title": "Sourcing Engine Scoring Methodology",
        "description": (
            "Products are evaluated against 7 weighted rules. "
            "Each rule produces a normalized score (0.0-1.0), a pass/fail status, "
            "and human-readable reasoning. The Opportunity Score is the weighted "
            "average of all rule scores, scaled to 0-100."
        ),
        "rules": [
            {
                "name": "Minimum ROI",
                "weight": 0.25,
                "severity": "critical",
                "metric": "ROI = (Net Profit / Total Cost) × 100",
                "default_minimum": "20%",
                "default_target": "50%",
                "description": "Measures return on capital invested. Critical for sourcing decisions.",
            },
            {
                "name": "Minimum Profit",
                "weight": 0.20,
                "severity": "critical",
                "metric": "Net Profit per Unit = Amazon Price - Total Cost",
                "default_minimum": "$2.00",
                "default_target": "$10.00",
                "description": "Low-profit products are fragile — small price changes wipe out margins.",
            },
            {
                "name": "Minimum Sales Volume",
                "weight": 0.15,
                "severity": "major",
                "metric": "Estimated Monthly Sales",
                "default_minimum": "300/month",
                "default_target": "2,000/month",
                "description": "Low-volume products may not justify the effort of listing and managing.",
            },
            {
                "name": "Competition Level",
                "weight": 0.15,
                "severity": "major",
                "metric": "New seller count, FBA percentage",
                "default_minimum": "≤20 sellers, ≤70% FBA",
                "default_target": "3-10 sellers",
                "description": "Too few sellers = low demand. Too many = price wars.",
            },
            {
                "name": "Buy Box Stability",
                "weight": 0.10,
                "severity": "minor",
                "metric": "Buy Box win rate percentage",
                "default_minimum": "60%",
                "default_target": "95%",
                "description": "Unstable Buy Box means aggressive repricing or seller churn.",
            },
            {
                "name": "Price Stability",
                "weight": 0.08,
                "severity": "minor",
                "metric": "Coefficient of Variation of Amazon price",
                "default_minimum": "≤15% CV",
                "default_target": "0% CV",
                "description": "Volatile prices make profit forecasting unreliable.",
            },
            {
                "name": "Inventory Availability",
                "weight": 0.07,
                "severity": "major",
                "metric": "Days of stock = Available Qty / Daily Sales",
                "default_minimum": "30 days",
                "default_target": "90 days",
                "description": "Low stock means stockouts and lost ranking.",
            },
        ],
        "scoring_formula": (
            "weighted_score = Σ(rule_score_i × weight_i) / Σ(weight_i); "
            "total_score = weighted_score × 100"
        ),
        "normalization": (
            "Below minimum: score = actual/minimum × 0.5 (0 to 0.5); "
            "At minimum: score = 0.5; "
            "Between min/target: linear interpolation 0.5 to 1.0; "
            "At or above target: score = 1.0"
        ),
        "viability_criteria": (
            "Critical rule failures < threshold (default: 1) AND "
            "Opportunity Score >= minimum (default: 40)"
        ),
        "confidence_levels": {
            "very_high": "500+ data points",
            "high": "200-499 data points",
            "medium": "50-199 data points",
            "low": "10-49 data points",
            "very_low": "<10 data points",
        },
        "risk_levels": {
            "very_low": "Score 85-100",
            "low": "Score 70-84",
            "medium": "Score 50-69",
            "high": "Score 30-49",
            "very_high": "Score 0-29 or critical rule failure",
        },
    }


# ═══════════════════════════════════════════════════════════════
# AI Reasoning Endpoints
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/evaluate/{product_id}/ai",
    response_model=ProductEvaluation,
    summary="Evaluate with AI reasoning",
    description=(
        "Evaluates a product using both rule-based scoring AND AI-powered "
        "reasoning. Returns the full evaluation with an AI-generated "
        "Buy/Watch/Avoid recommendation, pros/cons, risks, expected return, "
        "and natural language explanation. Requires an LLM provider to be configured."
    ),
)
async def evaluate_with_ai(
    product_id: UUID,
    days: int = Query(
        default=90, ge=30, le=365,
        description="Analysis window in days",
    ),
    provider: str | None = Query(
        default=None,
        description="LLM provider: anthropic, openai, ollama, or auto-detect",
    ),
    engine: SourcingEngine = Depends(get_sourcing_engine),
) -> ProductEvaluation:
    """Evaluate a product with AI-powered reasoning."""
    from app.ai import AIReasoningEngine, create_provider

    # Create LLM provider
    llm_provider = create_provider(provider_type=provider)
    if llm_provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No LLM provider available. Configure one of: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, or OLLAMA_BASE_URL "
                "environment variables, or specify a provider type."
            ),
        )

    # Create engine with AI reasoning
    ai_engine = AIReasoningEngine(llm_provider=llm_provider)
    engine_with_ai = SourcingEngine(
        repository=engine._repo,
        config=engine._config,
        ai_reasoning=ai_engine,
    )

    evaluation = await engine_with_ai.evaluate_product(product_id, days=days)
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID '{product_id}' not found or evaluation failed",
        )
    return evaluation


@router.get(
    "/ai/providers",
    summary="List available AI providers",
    description="Returns the list of configured and available LLM providers.",
)
async def list_ai_providers() -> dict[str, Any]:
    """List available AI providers."""
    import os

    providers = []

    # Check each provider
    if os.environ.get("ANTHROPIC_API_KEY"):
        providers.append({
            "name": "anthropic",
            "configured": True,
            "models": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"],
        })
    else:
        providers.append({"name": "anthropic", "configured": False, "models": []})

    if os.environ.get("OPENAI_API_KEY"):
        providers.append({
            "name": "openai",
            "configured": True,
            "models": ["gpt-4o", "gpt-4", "gpt-3.5-turbo"],
        })
    else:
        providers.append({"name": "openai", "configured": False, "models": []})

    if os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST"):
        providers.append({
            "name": "ollama",
            "configured": True,
            "models": ["llama3.2", "mistral", "gemma2"],
        })
    else:
        providers.append({"name": "ollama", "configured": False, "models": []})

    return {"providers": providers}


@router.get(
    "/ai/prompts",
    summary="List available prompt templates",
    description="Returns the list of registered prompt templates with versions.",
)
async def list_ai_prompts() -> dict[str, Any]:
    """List available prompt templates."""
    from app.ai.prompts import list_prompts
    return {"prompts": list_prompts()}
