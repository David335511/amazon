"""Research Agent — gather supplier and product intelligence.

The research agent sources data for the target ASIN: every known supplier offer
(unit price, shipping, landed cost, availability, MOQ, discount). It prefers the
`reverse_source` tool (reverse-sourcing engine) when wired through DI, and falls
back to shared-memory seed data otherwise.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class ResearchAgent(Agent):
    role = "research"
    display_name = "Research Agent"
    description = "Gathers supplier offers and product intelligence for an ASIN."
    capabilities: ClassVar[list[str]] = ["data_gathering", "supplier_intel"]
    default_tools: ClassVar[list[str]] = ["reverse_source", "supplier_scores"]
    depends_on: ClassVar[list[str]] = []

    async def run(self, context: Any) -> AgentResult:
        asin = context.task.get("asin")
        context.trace("research_start", "Gathering supplier and product data", asin=asin)

        offers = None
        if context.tool_registry is not None and context.tool_registry.has("reverse_source"):
            try:
                offers = await context.use_tool(
                    "reverse_source",
                    asin=asin,
                    quantity=context.task.get("quantity", 1),
                )
            except Exception:
                offers = None
        if offers is None:
            offers = context.recall("supplier_offers", [])
        # An empty result (e.g. no supplier plugins enabled) is treated as "no
        # data" and falls back to the injected seed so the pipeline still works.
        if not offers:
            offers = context.recall("supplier_offers", [])

        # Normalise each offer with a derived landed cost when missing.
        normalised: list[dict[str, Any]] = []
        for offer in offers:
            entry = dict(offer)
            if entry.get("landed_cost") is None:
                # Per-unit landed cost (quantity=1) so offers are comparable
                # across suppliers for matching / pricing / profit.
                if context.tool_registry is not None and context.tool_registry.has("landed_cost"):
                    try:
                        entry["landed_cost"] = await context.use_tool(
                            "landed_cost",
                            unit_price=entry.get("unit_price", 0.0),
                            shipping=entry.get("shipping_cost", 0.0),
                            quantity=1,
                        )
                    except Exception:
                        entry["landed_cost"] = round(
                            entry.get("unit_price", 0.0) + entry.get("shipping_cost", 0.0), 2
                        )
                else:
                    entry["landed_cost"] = round(
                        entry.get("unit_price", 0.0) + entry.get("shipping_cost", 0.0), 2
                    )
            normalised.append(entry)

        context.trace("research_data", f"Gathered {len(normalised)} supplier offers", asin=asin)
        data = {"asin": asin, "offers": normalised, "offer_count": len(normalised)}
        context.share("research", data)
        return AgentResult(
            role=self.role,
            summary=f"Researched {asin}: found {len(normalised)} supplier offers." if asin
            else f"Researched {len(normalised)} supplier offers.",
            data=data,
            recommendations=(
                [f"Evaluate the {len(normalised)} supplier offers for {asin}."] if normalised else
                ["No supplier offers found — configure supplier plugins or seed data."]
            ),
            confidence=0.8 if normalised else 0.4,
            risk_level="low" if normalised else "medium",
        )
