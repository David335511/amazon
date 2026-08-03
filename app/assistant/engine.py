"""Assistant engine — orchestrates retrieval + LLM to answer user questions.

Design decisions:
- RAG pattern: retrieve data FIRST, then call LLM with the context.
- Capability auto-detection from the question text.
- Each capability retrieves specific data needed for that question type.
- Falls back to rule-based answers if no LLM provider is available.
- All responses include retrieved data sources for transparency.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMProvider
from app.ai.prompts import get_prompt
from app.assistant.models import (
    AssistantCapability,
    AssistantQuery,
    AssistantResponse,
    RetrievedContext,
)
from app.assistant.retriever import AssistantRetriever
from app.core.logging import get_logger
from app.plugins.manager import PluginManager

if TYPE_CHECKING:
    from app.multilingual.manager import MultilingualManager

logger = get_logger(__name__)

# Capability keywords for auto-detection
CAPABILITY_KEYWORDS: dict[str, list[str]] = {
    "why_profitable": ["why profit", "why is this profit", "profitability", "profit driver", "what makes this profit", "how profit", "explain profit", "profitable"],
    "find_similar": ["similar product", "find similar", "comparable product", "alternative product", "like this", "similar to", "similar"],
    "predict_next_sale": ["predict sale", "forecast", "next sale", "sales prediction", "when will it sell", "sales forecast", "predict next", "sales"],
    "estimate_future_roi": ["future roi", "estimated roi", "projected roi", "roi estimate", "future profit", "will roi change", "roi next", "future"],
    "summarize_opportunities": ["summarize opportunity", "today opportunity", "best opportunity", "top opportunity", "opportunity summary", "what should i buy", "best deal", "top product", "opportunities", "today best"],
    "find_replacement_suppliers": ["replacement supplier", "alternative supplier", "find supplier", "new supplier", "supplier replacement", "better supplier", "cheaper supplier", "supplier"],
    "buy_more_inventory": ["buy more", "reorder", "restock", "inventory decision", "should i buy", "order more", "stock up", "buy inventory", "inventory"],
    "generate_purchase_order": ["purchase order", "create po", "generate po", "buy order", "order form", "create purchase", "purchase"],
    "explain_calculation": ["explain calculation", "how was this calculated", "show your work", "how did you get", "calculation breakdown", "explain how", "calculated", "calculation"],
}


class AssistantEngine:
    """Orchestrates retrieval + LLM to answer user questions.

    Usage:
        engine = AssistantEngine(db, llm_provider=provider)
        response = await engine.answer(query)
        print(response.answer)
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_provider: LLMProvider | None = None,
        plugin_manager: PluginManager | None = None,
        prompt_version: str = "assistant_v1",
        multilingual: MultilingualManager | None = None,
        language: str = "en",
    ) -> None:
        self._retriever = AssistantRetriever(
            db=db,
            plugin_manager=plugin_manager,
        )
        self._llm_provider = llm_provider
        self._prompt_version = prompt_version
        self._multilingual = multilingual
        self._language = language

    async def answer(self, query: AssistantQuery) -> AssistantResponse:
        """Answer a user question using retrieval + LLM.

        Args:
            query: The user's question with optional context.

        Returns:
            AssistantResponse with answer and data sources.
        """
        start = time.monotonic()

        # Step 1: Detect capability
        capability = query.capability or self._detect_capability(query.question)

        # Step 2: Retrieve relevant data
        contexts = await self._retrieve_for_capability(capability, query)

        # Step 3: Build prompt with context
        prompt_data = {
            "question": query.question,
            "capability": capability.value,
            "contexts": [c.model_dump() for c in contexts],
        }

        prompts = get_prompt(self._prompt_version, prompt_data)

        # Step 4: Generate answer
        if self._llm_provider is not None and prompts is not None:
            try:
                system_prompt, user_prompt = prompts
                # Prompt injection (English instruction): ask the model to reply in
                # the selected language. Reasoning stays English; only output is
                # localized. Keeps codes/ASINs/SKUs/numbers verbatim.
                if self._multilingual is not None and self._language != "en":
                    system_prompt = self._multilingual.build_system_instruction(
                        system_prompt, self._language,
                    )
                response = await self._llm_provider.generate_with_retry(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )

                parsed = self._parse_json_response(response.content)
                latency = (time.monotonic() - start) * 1000

                result = AssistantResponse(
                    answer=parsed.get("answer", "Analysis complete."),
                    capability=capability,
                    confidence=parsed.get("confidence", "medium"),
                    contexts=contexts if query.include_sources else [],
                    model_used=response.model,
                    provider_used=response.provider,
                    prompt_version=self._prompt_version,
                    latency_ms=round(latency, 2),
                    structured_data=parsed.get("structured_data"),
                )
                if self._multilingual is not None:
                    return self._multilingual.localize_labels(result, self._language)
                return result
            except Exception as exc:
                logger.warning("LLM answer failed, using fallback: %s", exc)

        # Step 5: Fallback — rule-based answer
        return self._fallback_answer(query, capability, contexts, start)

    # ═══════════════════════════════════════════════════════════════
    # Capability Detection
    # ═══════════════════════════════════════════════════════════════

    def _detect_capability(self, question: str) -> AssistantCapability:
        """Auto-detect the capability from the question text."""
        q_lower = question.lower()

        best_match = None
        best_score = 0

        for capability, keywords in CAPABILITY_KEYWORDS.items():
            for keyword in keywords:
                # Prefer exact substring matches (highest score)
                if keyword in q_lower:
                    score = len(keyword) * 100  # Substring match is strongest signal
                    if score > best_score:
                        best_score = score
                        best_match = capability
                else:
                    # Word-level matching as fallback
                    keyword_words = set(keyword.split())
                    question_words = set(q_lower.split())
                    common = keyword_words & question_words
                    # Require at least 60% word overlap
                    if len(common) >= 2 and len(common) / max(len(keyword_words), 1) >= 0.6:
                        score = len(common) * 10
                        if score > best_score:
                            best_score = score
                            best_match = capability

        if best_match:
            return AssistantCapability(best_match)

        return AssistantCapability.GENERAL_QUERY

    # ═══════════════════════════════════════════════════════════════
    # Retrieval
    # ═══════════════════════════════════════════════════════════════

    async def _retrieve_for_capability(
        self,
        capability: AssistantCapability,
        query: AssistantQuery,
    ) -> list[RetrievedContext]:
        """Retrieve data relevant to the detected capability."""
        contexts: list[RetrievedContext] = []
        product_id = query.product_id

        # If we have an ASIN but no product_id, look it up
        if product_id is None and query.asin:
            product_ctx = await self._retriever.get_product(asin=query.asin)
            if product_ctx:
                contexts.append(product_ctx)
                pid_str = product_ctx.data.get("id", "")
                if pid_str:
                    product_id = UUID(pid_str)

        if capability == AssistantCapability.WHY_PROFITABLE and product_id:
            contexts.extend(await self._retriever.get_profit_data(product_id))
            contexts.extend(await self._retriever.get_sales_data(product_id, query.days))
            contexts.extend(await self._retriever.get_competition_data(product_id))

        elif capability == AssistantCapability.FIND_SIMILAR and product_id:
            contexts.extend(await self._retriever.find_similar_products(product_id))
            if product_id:
                pc = await self._retriever.get_product(product_id=product_id)
                if pc:
                    contexts.append(pc)

        elif capability == AssistantCapability.PREDICT_NEXT_SALE and product_id:
            contexts.extend(await self._retriever.get_sales_data(product_id, query.days))
            contexts.extend(await self._retriever.get_price_history(product_id, query.days))

        elif capability == AssistantCapability.ESTIMATE_FUTURE_ROI and product_id:
            contexts.extend(await self._retriever.get_profit_data(product_id))
            contexts.extend(await self._retriever.get_price_history(product_id, query.days))
            contexts.extend(await self._retriever.get_competition_data(product_id))

        elif capability == AssistantCapability.SUMMARIZE_OPPORTUNITIES:
            contexts.extend(await self._retriever.get_recent_opportunities(days=query.days))

        elif capability == AssistantCapability.FIND_REPLACEMENT_SUPPLIERS and product_id:
            contexts.extend(await self._retriever.get_suppliers_for_product(product_id))
            contexts.extend(await self._retriever.get_all_suppliers())

        elif capability == AssistantCapability.BUY_MORE_INVENTORY and product_id:
            contexts.extend(await self._retriever.get_inventory_data(product_id))
            contexts.extend(await self._retriever.get_sales_data(product_id, query.days))
            contexts.extend(await self._retriever.get_suppliers_for_product(product_id))

        elif capability == AssistantCapability.GENERATE_PURCHASE_ORDER and product_id:
            contexts.extend(await self._retriever.get_profit_data(product_id))
            contexts.extend(await self._retriever.get_inventory_data(product_id))
            contexts.extend(await self._retriever.get_suppliers_for_product(product_id))

        elif capability == AssistantCapability.EXPLAIN_CALCULATION and product_id:
            contexts.extend(await self._retriever.get_profit_data(product_id))
            contexts.extend(await self._retriever.get_sales_data(product_id, query.days))

        else:
            # General query: get whatever we can
            if product_id:
                contexts.extend(await self._retriever.get_profit_data(product_id))
                contexts.extend(await self._retriever.get_sales_data(product_id, query.days))
                contexts.extend(await self._retriever.get_inventory_data(product_id))

        return contexts

    # ═══════════════════════════════════════════════════════════════
    # Fallback
    # ═══════════════════════════════════════════════════════════════

    def _fallback_answer(
        self,
        query: AssistantQuery,
        capability: AssistantCapability,
        contexts: list[RetrievedContext],
        start: float,
    ) -> AssistantResponse:
        """Generate a rule-based answer when LLM is unavailable.

        Uses localized templates when multilingual support is enabled.
        """
        latency = (time.monotonic() - start) * 1000

        if self._multilingual is not None:
            answer = self._multilingual.fallback_answer(
                query.question, contexts, self._language,
            )
        else:
            # English fallback template (no multilingual support configured).
            parts = [f"Analysis for: {query.question}", ""]
            for ctx in contexts:
                parts.append(f"• {ctx.summary}")
            if not contexts:
                parts.append("No data was found for this query. Try specifying a product ID or ASIN.")
            parts.append("")
            parts.append("This is a rule-based response. For deeper analysis, configure an LLM provider.")
            answer = "\n".join(parts)

        result = AssistantResponse(
            answer=answer,
            capability=capability,
            confidence="low",
            contexts=contexts if query.include_sources else [],
            model_used="rule-based",
            provider_used="fallback",
            prompt_version=self._prompt_version,
            latency_ms=round(latency, 2),
        )
        if self._multilingual is not None:
            return self._multilingual.localize_labels(result, self._language)
        return result

    # ═══════════════════════════════════════════════════════════════
    # JSON Parsing
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _parse_json_response(content: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        return json.loads(content)
