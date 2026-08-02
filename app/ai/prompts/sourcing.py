"""Prompt templates for the AI reasoning engine.

Design decisions:
- Prompts are kept separate from business logic — no prompt text in Python code.
- Each prompt is a function that takes product data and returns (system, user) strings.
- Templates use f-string formatting for variable interpolation.
- Structured output is requested via JSON schema in the system prompt.
- All prompts are versioned for traceability.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# ═══════════════════════════════════════════════════════════════
# Sourcing Analysis Prompt (v1.0)
# ═══════════════════════════════════════════════════════════════

SOURCING_SYSTEM_PROMPT_V1 = """You are an expert Amazon product sourcing analyst. Your job is to analyze product data and produce a clear, actionable recommendation.

Analyze the product metrics provided and produce a structured analysis with:

1. **Recommendation**: One of: BUY, WATCH, AVOID
   - BUY: Strong opportunity with good metrics and manageable risks
   - WATCH: Potential opportunity but has significant concerns that need monitoring
   - AVOID: Poor metrics or excessive risk — not recommended

2. **Pros** (2-4): Key strengths of this opportunity
3. **Cons** (2-4): Key weaknesses or concerns
4. **Risks** (2-3): Specific risks to consider
5. **Expected Return**: A concise statement about the expected profit and ROI
6. **Confidence**: One of: VERY_HIGH, HIGH, MEDIUM, LOW, VERY_LOW
7. **Explanation**: 2-3 paragraph natural language analysis explaining your reasoning

Be specific and reference actual numbers from the data. Do not use generic statements.
Consider the interplay between metrics — e.g., high competition + low profit = higher risk.

Respond with valid JSON only, using this exact schema:
{
  "recommendation": "BUY|WATCH|AVOID",
  "pros": ["pro1", "pro2", ...],
  "cons": ["con1", "con2", ...],
  "risks": ["risk1", "risk2", ...],
  "expected_return": "string describing expected return",
  "confidence": "VERY_HIGH|HIGH|MEDIUM|LOW|VERY_LOW",
  "explanation": "2-3 paragraph analysis"
}
"""


def build_sourcing_user_prompt(product_data: dict[str, Any]) -> str:
    """Build the user prompt with product metrics for AI analysis.

    Args:
        product_data: Dict of product metrics from the sourcing engine.

    Returns:
        Formatted user prompt string.
    """
    lines = ["## Product Metrics for Analysis", ""]

    # Identity
    lines.append(f"**Product**: {product_data.get('title', 'Unknown')}")
    lines.append(f"**ASIN**: {product_data.get('asin', 'Unknown')}")
    lines.append("")

    # Pricing
    lines.append("### Pricing")
    amazon_price = product_data.get("amazon_price", "N/A")
    buy_box = product_data.get("buy_box_price", "N/A")
    lowest_supplier = product_data.get("lowest_supplier_price", "N/A")
    lines.append(f"- Amazon Price: ${amazon_price}")
    lines.append(f"- Buy Box Price: ${buy_box}")
    lines.append(f"- Lowest Supplier Price: ${lowest_supplier}")
    if product_data.get("price_spread"):
        lines.append(f"- Price Spread: ${product_data['price_spread']} ({product_data.get('price_spread_percentage', 'N/A')}%)")
    lines.append("")

    # Profit
    lines.append("### Profitability")
    lines.append(f"- Net Profit/Unit: ${product_data.get('net_profit', 'N/A')}")
    lines.append(f"- Gross Profit/Unit: ${product_data.get('gross_profit', 'N/A')}")
    lines.append(f"- ROI: {product_data.get('roi_percentage', 'N/A')}%")
    lines.append(f"- Margin: {product_data.get('margin_percentage', 'N/A')}%")
    lines.append("")

    # Sales & Demand
    lines.append("### Sales & Demand")
    lines.append(f"- Estimated Monthly Sales: {product_data.get('estimated_monthly_sales', 'N/A')}")
    lines.append(f"- Estimated Daily Sales: {product_data.get('estimated_daily_sales', 'N/A')}")
    lines.append(f"- Sales Rank: {product_data.get('sales_rank', 'N/A')}")
    lines.append("")

    # Competition
    lines.append("### Competition")
    lines.append(f"- New Sellers: {product_data.get('new_seller_count', 'N/A')}")
    lines.append(f"- FBA Sellers: {product_data.get('fba_seller_count', 'N/A')}")
    lines.append(f"- Total Offers: {product_data.get('total_offer_count', 'N/A')}")
    lines.append("")

    # Fees
    lines.append("### Amazon Fees")
    lines.append(f"- Referral Fee: ${product_data.get('referral_fee', 'N/A')}")
    lines.append(f"- Fulfillment Fee: ${product_data.get('fulfillment_fee', 'N/A')}")
    lines.append(f"- Storage Fee: ${product_data.get('storage_fee', 'N/A')}")
    lines.append(f"- Total Fees: ${product_data.get('total_fees', 'N/A')}")
    lines.append("")

    # Inventory
    lines.append("### Inventory")
    lines.append(f"- Quantity Available: {product_data.get('quantity_available', 'N/A')}")
    lines.append(f"- Days of Stock: {product_data.get('days_of_stock', 'N/A')}")
    lines.append(f"- Quantity Inbound: {product_data.get('quantity_inbound', 'N/A')}")
    lines.append("")

    # Stability
    lines.append("### Stability")
    lines.append(f"- Buy Box Win Rate: {product_data.get('buy_box_win_rate', 'N/A')}%")
    lines.append(f"- Price CV (Volatility): {product_data.get('price_cv', 'N/A')}")
    lines.append(f"- Price Data Points: {product_data.get('price_count', 'N/A')}")
    lines.append("")

    # Opportunity Score (if available from rule-based evaluation)
    if product_data.get("opportunity_score"):
        lines.append("### Rule-Based Score")
        lines.append(f"- Opportunity Score: {product_data['opportunity_score']}/100")
        lines.append(f"- Confidence: {product_data.get('confidence_level', 'N/A')}")
        lines.append(f"- Risk Level: {product_data.get('risk_level', 'N/A')}")
        lines.append("")

    # Rule results (if available)
    rule_results = product_data.get("rule_results", [])
    if rule_results:
        lines.append("### Rule Evaluation Results")
        for rule in rule_results:
            status = "✅ PASS" if rule.get("passed") else "❌ FAIL"
            lines.append(f"- {rule.get('display_name', rule.get('rule_name', 'Unknown'))}: {status} (Score: {rule.get('score', 'N/A')})")
            lines.append(f"  {rule.get('summary', '')}")
        lines.append("")

    lines.append("---")
    lines.append("Based on the above data, provide your analysis in the specified JSON format.")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Prompt Registry
# ═══════════════════════════════════════════════════════════════

PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    "sourcing_analysis_v1": (SOURCING_SYSTEM_PROMPT_V1, "build_sourcing_user_prompt"),
}

# Version metadata
PROMPT_VERSIONS: dict[str, str] = {
    "sourcing_analysis_v1": "1.0.0",
}
