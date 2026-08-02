"""Tests for the AI reasoning module — providers, prompts, and reasoning engine.

Tests use mocked LLM responses to avoid requiring actual API keys.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
import pytest_asyncio

from app.ai.base import LLMConfig, LLMProvider, LLMResponse
from app.ai.prompts import get_prompt, list_prompts
from app.ai.prompts.sourcing import build_sourcing_user_prompt
from app.ai.reasoning import AIReasoningEngine, AIRecommendation, RecommendationAction
from app.sourcing.models import (
    ConfidenceLevel,
    OpportunityScore,
    ProductEvaluation,
    RiskLevel,
    RuleResult,
    RuleSeverity,
)


# ═══════════════════════════════════════════════════════════════
# Mock Provider
# ═══════════════════════════════════════════════════════════════


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    provider_name = "mock"

    def __init__(
        self,
        response_content: str = '{"recommendation": "BUY", "pros": ["Good ROI"], "cons": ["Low sales"], "risks": ["Competition"], "expected_return": "$5,000/month at 25% ROI", "confidence": "HIGH", "explanation": "Test analysis."}',
    ) -> None:
        super().__init__()
        self._response_content = response_content
        self._available = True

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content=self._response_content,
            model="mock-model",
            provider="mock",
            usage={"total_tokens": 100},
            finish_reason="stop",
            latency_ms=100.0,
        )

    async def is_available(self) -> bool:
        return self._available


# ═══════════════════════════════════════════════════════════════
# Prompt Tests
# ═══════════════════════════════════════════════════════════════


class TestPrompts:
    """Test prompt templates."""

    def test_build_sourcing_user_prompt(self) -> None:
        """Test building the sourcing user prompt."""
        data = {
            "title": "Test Product",
            "asin": "B0TEST",
            "amazon_price": "29.99",
            "net_profit": "5.00",
            "roi_percentage": "45",
            "estimated_monthly_sales": "1500",
            "new_seller_count": "8",
            "fba_seller_count": "5",
            "buy_box_win_rate": "75",
            "price_cv": "0.08",
            "days_of_stock": "60",
            "quantity_available": "500",
            "opportunity_score": 75,
            "confidence_level": "high",
            "risk_level": "low",
        }
        prompt = build_sourcing_user_prompt(data)
        assert "Test Product" in prompt
        assert "B0TEST" in prompt
        assert "29.99" in prompt
        assert "5.00" in prompt
        assert "45" in prompt
        assert "1500" in prompt
        assert "Pricing" in prompt
        assert "Profitability" in prompt
        assert "Competition" in prompt

    def test_get_prompt_valid(self) -> None:
        """Test getting a valid prompt."""
        result = get_prompt("sourcing_analysis_v1", {"title": "Test"})
        assert result is not None
        system, user = result
        assert "sourcing analyst" in system.lower()
        assert "Test" in user

    def test_get_prompt_invalid(self) -> None:
        """Test getting an invalid prompt returns None."""
        result = get_prompt("nonexistent_prompt", {})
        assert result is None

    def test_list_prompts(self) -> None:
        """Test listing prompts."""
        prompts = list_prompts()
        assert len(prompts) >= 1
        assert any(p["name"] == "sourcing_analysis_v1" for p in prompts)


# ═══════════════════════════════════════════════════════════════
# AI Reasoning Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestAIReasoningEngine:
    """Test the AI reasoning engine."""

    def test_parse_json_response(self) -> None:
        """Test parsing JSON from LLM response."""
        content = '{"recommendation": "BUY", "pros": ["Good"], "cons": [], "risks": [], "expected_return": "$5k", "confidence": "HIGH", "explanation": "Test."}'
        parsed = AIReasoningEngine._parse_json_response(content)
        assert parsed["recommendation"] == "BUY"
        assert parsed["confidence"] == "HIGH"

    def test_parse_json_with_code_block(self) -> None:
        """Test parsing JSON with markdown code block."""
        content = '```json\n{"recommendation": "WATCH", "pros": ["Good"], "cons": ["Bad"], "risks": ["Risk"], "expected_return": "$2k", "confidence": "MEDIUM", "explanation": "Test."}\n```'
        parsed = AIReasoningEngine._parse_json_response(content)
        assert parsed["recommendation"] == "WATCH"
        assert parsed["confidence"] == "MEDIUM"

    @pytest.mark.asyncio
    async def test_analyze_with_mock_provider(self) -> None:
        """Test analysis with a mock LLM provider."""
        provider = MockLLMProvider()
        engine = AIReasoningEngine(llm_provider=provider)

        data = {
            "title": "Test Product",
            "asin": "B0TEST",
            "amazon_price": "29.99",
            "net_profit": "5.00",
            "roi_percentage": "45",
            "estimated_monthly_sales": "1500",
            "new_seller_count": "8",
            "fba_seller_count": "5",
            "buy_box_win_rate": "75",
            "price_cv": "0.08",
            "days_of_stock": "60",
            "quantity_available": "500",
            "opportunity_score": 75,
            "confidence_level": "high",
            "risk_level": "low",
        }

        recommendation = await engine.analyze(data)
        assert recommendation.recommendation == RecommendationAction.BUY
        assert recommendation.confidence == ConfidenceLevel.HIGH
        assert recommendation.provider_used == "mock"

    @pytest.mark.asyncio
    async def test_analyze_with_invalid_json(self) -> None:
        """Test fallback when LLM returns invalid JSON."""
        provider = MockLLMProvider(response_content="not valid json")
        engine = AIReasoningEngine(llm_provider=provider)

        data = {
            "title": "Test",
            "asin": "B0TEST",
            "opportunity_score": 60,
            "confidence_level": "medium",
            "risk_level": "medium",
            "rule_results": [
                {
                    "rule_name": "minimum_roi",
                    "display_name": "Minimum ROI",
                    "score": 0.8,
                    "passed": True,
                    "summary": "Good ROI of 45%",
                    "severity": "critical",
                },
            ],
        }

        recommendation = await engine.analyze(data)
        # Should fall back to rule-based
        assert recommendation.provider_used == "fallback"
        assert recommendation.recommendation in (
            RecommendationAction.BUY,
            RecommendationAction.WATCH,
            RecommendationAction.AVOID,
        )

    @pytest.mark.asyncio
    async def test_analyze_without_provider(self) -> None:
        """Test fallback when no LLM provider is available."""
        engine = AIReasoningEngine(llm_provider=None)

        data = {
            "title": "Test",
            "asin": "B0TEST",
            "opportunity_score": 30,
            "confidence_level": "low",
            "risk_level": "high",
            "rule_results": [],
        }

        recommendation = await engine.analyze(data)
        assert recommendation.provider_used == "fallback"
        assert recommendation.recommendation == RecommendationAction.AVOID

    def test_build_product_data(self) -> None:
        """Test building product data from evaluation."""
        evaluation = ProductEvaluation(
            product_id=UUID("00000000-0000-0000-0000-000000000001"),
            asin="B0TEST",
            title="Test Product",
            opportunity_score=OpportunityScore(
                total_score=Decimal("75.00"),
                weighted_score=Decimal("0.75"),
                rule_results=[
                    RuleResult(
                        rule_name="minimum_roi",
                        display_name="Minimum ROI",
                        severity=RuleSeverity.CRITICAL,
                        weight=Decimal("0.25"),
                        score=Decimal("0.8"),
                        passed=True,
                        summary="Good ROI of 45%",
                        actual_value="45%",
                        threshold_value="20%",
                        target_value="50%",
                    ),
                ],
                critical_failures=0,
                is_viable=True,
            ),
            confidence=ConfidenceLevel.HIGH,
            risk_level=RiskLevel.LOW,
            summary="Test summary",
        )

        data = AIReasoningEngine.build_product_data(evaluation)
        assert data["title"] == "Test Product"
        assert data["asin"] == "B0TEST"
        assert data["opportunity_score"] == 75.0
        assert data["confidence_level"] == "high"
        assert data["risk_level"] == "low"
        assert len(data["rule_results"]) == 1
        assert data["rule_results"][0]["rule_name"] == "minimum_roi"

    @pytest.mark.asyncio
    async def test_fallback_reasoning_buy(self) -> None:
        """Test fallback produces BUY for high scores."""
        engine = AIReasoningEngine(llm_provider=None)
        data = {
            "title": "Great Product",
            "asin": "B0GREAT",
            "opportunity_score": 85,
            "confidence_level": "high",
            "risk_level": "low",
            "net_profit": 5.00,
            "roi_percentage": 50,
            "estimated_monthly_sales": 2000,
            "rule_results": [
                {
                    "rule_name": "minimum_roi",
                    "display_name": "Minimum ROI",
                    "score": 0.9,
                    "passed": True,
                    "summary": "Excellent ROI of 50%",
                    "severity": "critical",
                },
            ],
        }
        rec = await engine.analyze(data)
        assert rec.recommendation == RecommendationAction.BUY

    @pytest.mark.asyncio
    async def test_fallback_reasoning_avoid(self) -> None:
        """Test fallback produces AVOID for low scores."""
        engine = AIReasoningEngine(llm_provider=None)
        data = {
            "title": "Bad Product",
            "asin": "B0BAD",
            "opportunity_score": 20,
            "confidence_level": "low",
            "risk_level": "high",
            "net_profit": 0.50,
            "roi_percentage": 5,
            "estimated_monthly_sales": 50,
            "rule_results": [
                {
                    "rule_name": "minimum_roi",
                    "display_name": "Minimum ROI",
                    "score": 0.1,
                    "passed": False,
                    "summary": "ROI of 5% is below minimum of 20%",
                    "severity": "critical",
                },
            ],
        }
        rec = await engine.analyze(data)
        assert rec.recommendation == RecommendationAction.AVOID


# ═══════════════════════════════════════════════════════════════
# Provider Tests
# ═══════════════════════════════════════════════════════════════


class TestLLMProviders:
    """Test LLM provider implementations."""

    def test_mock_provider(self) -> None:
        """Test the mock provider."""
        provider = MockLLMProvider()
        assert provider.provider_name == "mock"

    @pytest.mark.asyncio
    async def test_mock_provider_generate(self) -> None:
        """Test mock provider generates response."""
        provider = MockLLMProvider()
        response = await provider.generate(
            system_prompt="Test system",
            user_prompt="Test user",
        )
        assert response.content is not None
        assert response.model == "mock-model"
        assert response.provider == "mock"
        assert response.latency_ms > 0

    @pytest.mark.asyncio
    async def test_mock_provider_retry(self) -> None:
        """Test retry logic with mock provider."""
        provider = MockLLMProvider()
        response = await provider.generate_with_retry(
            system_prompt="Test",
            user_prompt="Test",
        )
        assert response.content is not None

    @pytest.mark.asyncio
    async def test_create_provider_no_key(self) -> None:
        """Test create_provider returns None when no keys are set."""
        from app.ai.providers import create_provider
        with patch.dict("os.environ", {}, clear=True):
            provider = create_provider()
            assert provider is None

    @pytest.mark.asyncio
    async def test_create_provider_unknown_type(self) -> None:
        """Test create_provider raises error for unknown type."""
        from app.ai.providers import create_provider
        with pytest.raises(ValueError, match="Unknown provider type"):
            create_provider(provider_type="unknown")
