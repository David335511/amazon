"""AI Assistant API routes — answer questions using retrieval + LLM.

Endpoints:
- POST /assistant/ask — Ask a question
- GET /assistant/capabilities — List available capabilities
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    Query,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import create_provider
from app.assistant.engine import AssistantEngine
from app.assistant.models import AssistantQuery, AssistantResponse
from app.core.database import get_db
from app.core.dependencies import get_multilingual_manager
from app.core.logging import get_logger
from app.multilingual.manager import MultilingualManager

logger = get_logger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])

ManagerDep = Annotated[MultilingualManager, Depends(get_multilingual_manager)]


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
    multilingual: ManagerDep,
    provider: str | None = Query(
        default=None,
        description="LLM provider: anthropic, openai, ollama, or auto-detect",
    ),
    lang: str | None = Query(
        default=None,
        description="Response language: en, zh-CN (overrides body/request resolution)",
    ),
    lang_cookie: str | None = Cookie(default=None, alias="lang"),
    accept_language: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AssistantResponse:
    """Ask the AI assistant a question, in the selected language.

    The response language resolves with priority: ``?lang=``/body ``language`` >
    ``lang`` cookie > ``Accept-Language`` header > stored preference > default. AI
    reasoning stays English internally; only the final answer is produced in the
    selected language.
    """
    resolved = await multilingual.resolve_current(
        query=lang or query.language,
        cookie=lang_cookie,
        header=_parse_accept_language(accept_language),
    )

    # Create LLM provider if specified
    llm_provider = create_provider(provider_type=provider)

    # Create engine
    engine = AssistantEngine(
        db=db,
        llm_provider=llm_provider,
        prompt_version="assistant_v1",
        multilingual=multilingual,
        language=resolved,
    )

    # Answer
    response = await engine.answer(query)
    return response


def _parse_accept_language(header: str | None) -> str | None:
    if not header:
        return None
    return header.split(",")[0].split(";")[0].strip()


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
