"""AI reasoning engine — uses LLM to analyze product data and produce recommendations.

Design decisions:
- The engine is provider-agnostic — any LLMProvider implementation works.
- Structured output is parsed from JSON in the LLM response.
- Falls back to rule-based reasoning if no LLM provider is available.
- All prompts are loaded from the prompt registry — no prompt text in this file.
- The engine is stateless — all data is passed in.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.base import LLMConfig, LLMProvider, LLMResponse
from app.ai.prompts import get_prompt
from app.core.logging import get_logger
from app.sourcing.models import (
    ConfidenceLevel,
    OpportunityScore,
    ProductEvaluation,
    RiskLevel,
    RuleResult,
)

logger = get_logger(__name__)


class RecommendationAction(str, Enum):
    """AI-generated recommendation for a product."""

    BUY = "BUY"
    WATCH = "WATCH"
    AVOID = "AVOID"


class AIRecommendation(BaseModel):
    """Structured recommendation from the AI reasoning engine.

    This is the parsed output from the LLM, validated by Pydantic.
    """

    recommendation: RecommendationAction = Field(
        ..., description="BUY, WATCH, or AVOID",
    )
    pros: list[str] = Field(
        default_factory=list, description="Key strengths (2-4 items)",
    )
    cons: list[str] = Field(
        default_factory=list, description="Key weaknesses (2-4 items)",
    )
    risks: list[str] = Field(
        default_factory=list, description="Specific risks (2-3 items)",
    )
    expected_return: str = Field(
        ..., description="Expected profit and ROI summary",
    )
    confidence: ConfidenceLevel = Field(
        ..., description="Confidence in this recommendation",
    )
    explanation: str = Field(
        ..., description="2-3 paragraph natural language analysis",
    )

    # Metadata
    model_used: str = Field(default="", description="LLM model used")
    provider_used: str = Field(default="", description="LLM provider used")
    latency_ms: float = Field(default=0, description="LLM response time")
    prompt_version: str = Field(
        default="sourcing_analysis_v1",
        description="Prompt template version used",
    )


class AIReasoningEngine:
    """Orchestrates AI-powered product analysis.

    Uses an LLM provider to analyze product metrics and produce
    structured recommendations. Falls back to rule-based logic
    if no LLM provider is available.

    Usage:
        engine = AIReasoningEngine(llm_provider=provider)
        recommendation = await engine.analyze(product_data)
        print(f"Recommendation: {recommendation.recommendation}")
        print(f"Explanation: {recommendation.explanation}")
    """

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        prompt_name: str = "sourcing_analysis_v1",
    ) -> None:
        self._provider = llm_provider
        self._prompt_name = prompt_name

    async def analyze(
        self,
        product_data: dict[str, Any],
    ) -> AIRecommendation:
        """Analyze product data and produce a recommendation.

        Args:
            product_data: Dict of product metrics. Should include:
                - title, asin, amazon_price, buy_box_price
                - lowest_supplier_price, net_profit, gross_profit
                - roi_percentage, margin_percentage
                - estimated_monthly_sales, estimated_daily_sales
                - new_seller_count, fba_seller_count
                - referral_fee, fulfillment_fee, total_fees
                - quantity_available, days_of_stock
                - buy_box_win_rate, price_cv
                - opportunity_score, confidence_level, risk_level (optional)
                - rule_results (optional)

        Returns:
            AIRecommendation with structured analysis.
        """
        if self._provider is None:
            return self._fallback_reasoning(product_data)

        try:
            return await self._llm_analysis(product_data)
        except Exception as exc:
            logger.warning("LLM analysis failed, falling back to rule-based: %s", exc)
            return self._fallback_reasoning(product_data)

    async def _llm_analysis(
        self,
        product_data: dict[str, Any],
    ) -> AIRecommendation:
        """Use LLM to analyze product data."""
        start = time.monotonic()

        # Get prompts from registry
        prompts = get_prompt(self._prompt_name, product_data)
        if prompts is None:
            return self._fallback_reasoning(product_data)

        system_prompt, user_prompt = prompts

        # Call LLM
        response = await self._provider.generate_with_retry(  # type: ignore[union-attr]
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        latency = (time.monotonic() - start) * 1000

        # Parse JSON response
        try:
            parsed = self._parse_json_response(response.content)
            # Normalize enum values to lowercase
            if "confidence" in parsed and isinstance(parsed["confidence"], str):
                parsed["confidence"] = parsed["confidence"].lower()
            if "recommendation" in parsed and isinstance(parsed["recommendation"], str):
                parsed["recommendation"] = parsed["recommendation"].upper()
            recommendation = AIRecommendation(
                **parsed,
                model_used=response.model,
                provider_used=response.provider,
                latency_ms=round(latency, 2),
                prompt_version=self._prompt_name,
            )
            return recommendation
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse LLM response: %s", exc)
            return self._fallback_reasoning(product_data)

    def _fallback_reasoning(
        self,
        product_data: dict[str, Any],
    ) -> AIRecommendation:
        """Fallback reasoning when LLM is unavailable.

        Uses the rule-based opportunity score to generate a basic recommendation.
        """
        score = product_data.get("opportunity_score", 50)
        if isinstance(score, Decimal):
            score = float(score)

        # Determine recommendation from score
        if score >= 70:
            recommendation = RecommendationAction.BUY
        elif score >= 40:
            recommendation = RecommendationAction.WATCH
        else:
            recommendation = RecommendationAction.AVOID

        # Build basic pros/cons from rule results
        rule_results = product_data.get("rule_results", [])
        pros = []
        cons = []
        risks = []

        for rule in rule_results:
            if isinstance(rule, dict):
                passed = rule.get("passed", False)
                summary = rule.get("summary", "")
                display = rule.get("display_name", rule.get("rule_name", ""))
                if passed and summary:
                    pros.append(f"{display}: {summary}")
                elif not passed and summary:
                    cons.append(f"{display}: {summary}")
                    risks.append(f"Risk from {display.lower()}")

        # Determine confidence
        confidence = product_data.get("confidence_level", ConfidenceLevel.MEDIUM)
        if isinstance(confidence, str):
            try:
                confidence = ConfidenceLevel(confidence)
            except ValueError:
                confidence = ConfidenceLevel.MEDIUM

        # Expected return
        net_profit = product_data.get("net_profit", 0)
        roi = product_data.get("roi_percentage", 0)
        monthly_sales = product_data.get("estimated_monthly_sales", 0)
        expected_return = (
            f"${float(net_profit) * int(monthly_sales):,.2f}/month "
            f"at {roi}% ROI (rule-based estimate)"
        )

        # Explanation
        explanation = self._build_fallback_explanation(
            product_data.get("title", "Unknown"),
            recommendation,
            score,
            pros,
            cons,
        )

        return AIRecommendation(
            recommendation=recommendation,
            pros=pros[:4],
            cons=cons[:4],
            risks=risks[:3],
            expected_return=expected_return,
            confidence=confidence,
            explanation=explanation,
            model_used="rule-based",
            provider_used="fallback",
            prompt_version=self._prompt_name,
        )

    def _build_fallback_explanation(
        self,
        title: str,
        recommendation: RecommendationAction,
        score: float,
        pros: list[str],
        cons: list[str],
    ) -> str:
        """Build a natural language explanation from rule results."""
        parts = [f"Analysis of \"{title}\" (score: {score:.1f}/100):"]

        if recommendation == RecommendationAction.BUY:
            parts.append(
                f"This product scores {score:.1f}/100 and is recommended for purchase. "
                f"It has {len(pros)} key strengths and manageable risks."
            )
        elif recommendation == RecommendationAction.WATCH:
            parts.append(
                f"This product scores {score:.1f}/100 and is worth monitoring. "
                f"It has both strengths and concerns that warrant attention before committing."
            )
        else:
            parts.append(
                f"This product scores {score:.1f}/100 and is not currently recommended. "
                f"The risks and weaknesses outweigh the potential returns."
            )

        if pros:
            parts.append(f"Strengths: {'; '.join(pros[:3])}")
        if cons:
            parts.append(f"Concerns: {'; '.join(cons[:3])}")

        parts.append(
            "This analysis is based on rule-based evaluation as no AI provider "
            "was available. For deeper analysis, configure an LLM provider."
        )

        return "\n\n".join(parts)

    @staticmethod
    def _parse_json_response(content: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        # Remove markdown code block markers if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()
        return json.loads(content)

    @staticmethod
    def build_product_data(
        evaluation: ProductEvaluation,
    ) -> dict[str, Any]:
        """Build a flat product data dict from a ProductEvaluation.

        This converts the structured evaluation into the flat dict
        expected by the prompt builder.
        """
        score = evaluation.opportunity_score
        data: dict[str, Any] = {
            "title": evaluation.title,
            "asin": evaluation.asin,
            "opportunity_score": float(score.total_score),
            "confidence_level": evaluation.confidence.value,
            "risk_level": evaluation.risk_level.value,
            "rule_results": [
                {
                    "rule_name": r.rule_name,
                    "display_name": r.display_name,
                    "score": float(r.score),
                    "passed": r.passed,
                    "summary": r.summary,
                    "severity": r.severity.value,
                }
                for r in score.rule_results
            ],
        }

        # Extract metrics from rule results and strengths/weaknesses
        for rule in score.rule_results:
            if rule.rule_name == "minimum_roi":
                data["roi_percentage"] = rule.actual_value
            elif rule.rule_name == "minimum_profit":
                data["net_profit"] = rule.actual_value
            elif rule.rule_name == "minimum_sales":
                data["estimated_monthly_sales"] = rule.actual_value
            elif rule.rule_name == "competition":
                data["new_seller_count"] = rule.actual_value
            elif rule.rule_name == "buy_box_stability":
                data["buy_box_win_rate"] = rule.actual_value
            elif rule.rule_name == "price_stability":
                data["price_cv"] = rule.actual_value
            elif rule.rule_name == "inventory_availability":
                data["days_of_stock"] = rule.actual_value

        return data
