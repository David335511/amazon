"""AI Assistant API routes — answer questions using retrieval + LLM.

Endpoints:
- POST /assistant/ask — Ask a question
- GET /assistant/capabilities — List available capabilities
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import create_provider
from app.assistant.engine import AssistantEngine, CAPABILITY_KEYWORDS
from app.assistant.models import AssistantCapability, AssistantQuery, AssistantResponse
from app.core.database import get_db
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post(
    "/ask",
    response_model=AssistantResponse,
    summary="Ask the AI assistant a question",
    description=(
        "Ask any question about your products, suppliers, or opportunities. "
        "The assistant retrieves relevant data from the database before calling "
        "an LLM to generate a natural language answer. Supports multiple LLM providers."
    ),
)
async def ask_assistant(
    query: AssistantQuery,
    provider: str | None = Query(
        default=None,
        description="LLM provider: anthropic, openai, ollama, or auto-detect",
    ),
    db: AsyncSession = Depends(get_db),
) -> AssistantResponse:
    """Ask the AI assistant a question."""
    # Create LLM provider if specified
    llm_provider = create_provider(provider_type=provider)

    # Create engine
    engine = AssistantEngine(
        db=db,
        llm_provider=llm_provider,
        prompt_version="assistant_v1",
    )

    # Answer
    response = await engine.answer(query)
    return response


@router.get(
    "/capabilities",
    summary="List assistant capabilities",
    description="Returns the list of capabilities the assistant can perform.",
)
async def list_capabilities() -> dict[str, Any]:
    """List all assistant capabilities with descriptions and example questions."""
    capabilities = [
        {
            "name": "why_profitable",
            "description": "Explain why a product is profitable, breaking down price, costs, fees, and margins",
            "example_questions": ["Why is this product profitable?", "What makes this ASIN profitable?", "Explain the profitability of B0TEST"],
            "data_required": "product_id or asin",
        },
        {
            "name": "find_similar",
            "description": "Find products similar to a given product by category and price range",
            "example_questions": ["Find similar products to this one", "What are comparable products?", "Show me alternatives like B0TEST"],
            "data_required": "product_id or asin",
        },
        {
            "name": "predict_next_sale",
            "description": "Predict future sales based on historical trends",
            "example_questions": ["When will this product sell next?", "Predict next month's sales", "Sales forecast for B0TEST"],
            "data_required": "product_id or asin",
        },
        {
            "name": "estimate_future_roi",
            "description": "Estimate future ROI based on price trends and market conditions",
            "example_questions": ["What will the ROI be next quarter?", "Estimate future ROI", "Will this product remain profitable?"],
            "data_required": "product_id or asin",
        },
        {
            "name": "summarize_opportunities",
            "description": "Summarize today's best sourcing opportunities",
            "example_questions": ["What are today's best opportunities?", "Summarize top products to buy", "Show me the best deals today"],
            "data_required": "none",
        },
        {
            "name": "find_replacement_suppliers",
            "description": "Find alternative suppliers with better pricing or terms",
            "example_questions": ["Find a replacement supplier", "Are there cheaper suppliers?", "Who else supplies this product?"],
            "data_required": "product_id or asin",
        },
        {
            "name": "buy_more_inventory",
            "description": "Calculate whether to reorder inventory and how much",
            "example_questions": ["Should I buy more inventory?", "When should I reorder?", "How much stock should I order?"],
            "data_required": "product_id or asin",
        },
        {
            "name": "generate_purchase_order",
            "description": "Generate a purchase order with line items and totals",
            "example_questions": ["Generate a purchase order", "Create a PO for this product", "I need to order more units"],
            "data_required": "product_id or asin, quantity",
        },
        {
            "name": "explain_calculation",
            "description": "Explain how a specific calculation was derived step by step",
            "example_questions": ["How was the ROI calculated?", "Explain the profit calculation", "Show me the math behind this"],
            "data_required": "product_id or asin",
        },
        {
            "name": "general_query",
            "description": "General questions about products, data, or the platform",
            "example_questions": ["Tell me about this product", "What data do you have?", "How is the market doing?"],
            "data_required": "varies",
        },
    ]

    return {
        "capabilities": capabilities,
        "total": len(capabilities),
        "prompt_version": "assistant_v1",
    }
