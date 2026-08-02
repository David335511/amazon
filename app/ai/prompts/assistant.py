"""Prompt templates for the AI assistant — version-controlled, separate from business logic.

Each capability has a dedicated system prompt that instructs the LLM
how to answer that type of question using the retrieved data.
"""

from __future__ import annotations

from typing import Any

# ═══════════════════════════════════════════════════════════════
# Assistant System Prompt (v1.0)
# ═══════════════════════════════════════════════════════════════

ASSISTANT_SYSTEM_PROMPT_V1 = """You are an expert Amazon product sourcing assistant. Your job is to answer user questions about products, profitability, sales, inventory, and suppliers using the data provided.

RULES:
1. ONLY use the data provided in the context below. Do not make up numbers.
2. If the data is insufficient to answer, say so clearly.
3. Show your work — explain which numbers you used and how you calculated.
4. Be specific — reference actual dollar amounts, percentages, and dates.
5. If you make assumptions, state them explicitly.
6. Format your response in clear paragraphs with bullet points where helpful.
7. Always include a confidence level based on data quality and quantity.

CAPABILITIES:
- why_profitable: Explain profit drivers using price, cost, fee, and sales data
- find_similar: Find products in same category with similar price
- predict_next_sale: Forecast sales using historical trends
- estimate_future_roi: Project ROI based on price trends and cost stability
- summarize_opportunities: Summarize top opportunities from profit data
- find_replacement_suppliers: Find alternative suppliers with better terms
- buy_more_inventory: Calculate reorder timing and quantity
- generate_purchase_order: Create a PO with line items and totals
- explain_calculation: Show step-by-step how a number was derived

Respond with valid JSON only, using this exact schema:
{
  "answer": "Your detailed answer here...",
  "confidence": "very_high|high|medium|low|very_low",
  "structured_data": { ... any structured data extracted from the answer ... }
}
"""


def build_assistant_user_prompt(
    question: str,
    capability: str,
    contexts: list[dict[str, Any]],
) -> str:
    """Build the user prompt with retrieved context for the LLM.

    Args:
        question: The user's question.
        capability: The detected capability.
        contexts: Retrieved data contexts.

    Returns:
        Formatted user prompt string.
    """
    lines = [f"## User Question\n{question}\n", f"## Capability\n{capability}\n"]

    if contexts:
        lines.append("## Retrieved Data Context")
        for i, ctx in enumerate(contexts):
            lines.append(f"\n### Context {i+1}: {ctx.get('source', 'unknown')}")
            lines.append(f"Summary: {ctx.get('summary', '')}")
            data = ctx.get('data', {})
            if data:
                import json
                lines.append(f"Data: ```json\n{json.dumps(data, indent=2, default=str)}\n```")
        lines.append("")

    lines.append("---")
    lines.append("Using ONLY the data above, answer the user's question. If the data is insufficient, say so.")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Prompt Registry
# ═══════════════════════════════════════════════════════════════

ASSISTANT_PROMPTS: dict[str, tuple[str, str]] = {
    "assistant_v1": (ASSISTANT_SYSTEM_PROMPT_V1, "build_assistant_user_prompt"),
}

ASSISTANT_PROMPT_VERSIONS: dict[str, str] = {
    "assistant_v1": "1.0.0",
}
