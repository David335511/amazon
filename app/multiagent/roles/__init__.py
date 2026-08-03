"""The built-in specialist agents.

`AgentRegistry.discover()` imports this package and collects every `Agent`
subclass with a non-empty ``role``. To add a new agent: write a new module here,
import its class in this file, and it is automatically available to the
supervisor, memory sharing, delegation and evaluation — **no engine changes**.
"""

from __future__ import annotations

from app.multiagent.roles.forecast import ForecastAgent
from app.multiagent.roles.inventory import InventoryAgent
from app.multiagent.roles.matching import MatchingAgent
from app.multiagent.roles.negotiation import NegotiationAgent
from app.multiagent.roles.planner import PlannerAgent
from app.multiagent.roles.pricing import PricingAgent
from app.multiagent.roles.profit import ProfitAgent
from app.multiagent.roles.reporting import ReportingAgent
from app.multiagent.roles.research import ResearchAgent
from app.multiagent.roles.risk import RiskAgent

__all__ = [
    "ForecastAgent",
    "InventoryAgent",
    "MatchingAgent",
    "NegotiationAgent",
    "PlannerAgent",
    "PricingAgent",
    "ProfitAgent",
    "ReportingAgent",
    "ResearchAgent",
    "RiskAgent",
]
