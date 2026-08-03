"""Reporting Agent — consolidate every specialist's findings.

Runs last and reads the shared memory produced by all earlier agents to assemble
a human-readable report and a concise executive summary with the single most
important recommendation.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult

_SECTIONS = [
    ("research", "Research"),
    ("matching", "Matching"),
    ("forecast", "Forecast"),
    ("pricing", "Pricing"),
    ("profit", "Profit"),
    ("risk", "Risk"),
    ("negotiation", "Negotiation"),
    ("inventory", "Inventory"),
]


class ReportingAgent(Agent):
    role = "reporting"
    display_name = "Reporting Agent"
    description = "Consolidates all specialist findings into a report and summary."
    capabilities: ClassVar[list[str]] = ["reporting", "summarization"]
    depends_on: ClassVar[list[str]] = ["research", "matching", "forecast", "pricing", "profit",
                  "risk", "negotiation", "inventory"]

    async def run(self, context: Any) -> AgentResult:
        asin = context.task.get("asin")
        context.trace("report_start", "Consolidating specialist findings")

        lines: list[str] = []
        for key, title in _SECTIONS:
            section = context.recall(key)
            if not section:
                continue
            lines.append(f"## {title}")
            summary = section.get("summary")
            if summary:
                lines.append(f"- {summary}")
            data_keys = section.get("data", {})
            if data_keys:
                lines.append(f"- data: {self._compact(data_keys)}")

        report = "\n".join(lines) if lines else "No specialist findings were produced."
        top = self._top_recommendation(context)
        summary = f"Report for {asin}: {top}" if asin else f"Report: {top}"

        context.trace("report_ready", "Report assembled", sections=len(lines))
        data = {"report": report, "summary": summary, "top_recommendation": top}
        context.share("reporting", data)
        return AgentResult(
            role=self.role,
            summary=summary,
            data=data,
            recommendations=[top],
            confidence=0.9,
        )

    @staticmethod
    def _top_recommendation(context: Any) -> str:
        profit = context.recall("profit", {})
        risk = context.recall("risk", {})
        matching = context.recall("matching", {})
        inventory = context.recall("inventory", {})
        if matching.get("best_supplier") is None:
            return "No suitable supplier found — expand sourcing options first."
        if risk.get("risk_level") == "high":
            return "High risk: mitigate before committing capital."
        if profit.get("margin_pct", 0.0) < 0.05:
            return "Thin margin: reconsider price or source a cheaper supplier."
        if inventory.get("action") == "reorder":
            return f"Proceed with {matching['best_supplier']}; reorder {inventory.get('reorder_qty')} units."
        return f"Proceed with {matching['best_supplier']} at {profit.get('recommended_price')}."

    @staticmethod
    def _compact(data: dict[str, Any]) -> str:
        return ", ".join(f"{k}={v}" for k, v in list(data.items())[:6])
