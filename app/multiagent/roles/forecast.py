"""Forecast Agent — demand forecasting.

Produces a demand forecast for the target product. Prefers the `forecast` tool
(forecasting engine) when wired through DI; otherwise derives a deterministic
baseline from seed data or task inputs, so the pipeline always has a forecast to
work with.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.multiagent.base import Agent, AgentResult


class ForecastAgent(Agent):
    role = "forecast"
    display_name = "Forecast Agent"
    description = "Forecasts demand for a product over a horizon."
    capabilities: ClassVar[list[str]] = ["forecasting", "demand_estimation"]
    default_tools: ClassVar[list[str]] = ["forecast"]
    depends_on: ClassVar[list[str]] = ["research"]

    async def run(self, context: Any) -> AgentResult:
        asin = context.task.get("asin")
        context.trace("forecast_start", "Forecasting demand", asin=asin)

        forecast = None
        if context.tool_registry is not None and context.tool_registry.has("forecast"):
            try:
                forecast = await context.use_tool("forecast", asin=asin)
            except Exception:
                forecast = None
        if forecast is None:
            forecast = context.recall("forecast_data") or self._baseline(context)

        context.trace(
            "forecast_ready",
            f"Forecast {forecast.get('units')} units",
            units=forecast.get("units"),
            horizon=forecast.get("horizon"),
        )
        data = dict(forecast)
        data["asin"] = asin
        context.share("forecast", data)
        return AgentResult(
            role=self.role,
            summary=f"Forecast ~{forecast.get('units')} units over {forecast.get('horizon')} period(s).",
            data=data,
            recommendations=[
                f"Plan for {forecast.get('units')} units in the next {forecast.get('horizon')} period(s)."
            ],
            confidence=forecast.get("confidence", 0.7),
            risk_level="low" if forecast.get("confidence", 0.7) >= 0.7 else "medium",
        )

    @staticmethod
    def _baseline(context: Any) -> dict[str, Any]:
        units = context.task.get("expected_units", 100)
        base = context.recall("base_demand")
        if isinstance(base, dict):
            units = base.get("units", units)
        horizon = context.task.get("horizon", 1)
        trend = context.task.get("trend", 0.05)
        confidence = context.task.get("forecast_confidence", 0.7)
        return {
            "units": max(0, round(units * (1 + trend))),
            "horizon": horizon,
            "trend": trend,
            "confidence": confidence,
        }
