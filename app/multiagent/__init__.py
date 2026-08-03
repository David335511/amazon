"""Multi-agent orchestration framework.

A pluggable, collaborative set of specialist agents (research, matching,
pricing, profit, forecast, risk, negotiation, inventory, reporting, planner)
that work together on a sourcing/fulfilment task.

Collaboration capabilities:
- **task delegation**   — an agent hands a subtask to another via the registry.
- **memory sharing**    — agents read/write a shared context (and optionally the
                         AI memory system).
- **reasoning traces**  — every agent records its deliberation for replay.
- **tool usage**        — agents call registered tools (reverse sourcing,
                         forecasting, supplier intel, pure-math helpers).
- **parallel execution**— the supervisor runs independent agents concurrently
                         as dependency-DAG waves.
- **agent supervision** — the planner decomposes the task; the supervisor
                         monitors and evaluates each agent.
- **agent evaluation**  — each run gets a quality score; per-role stats aggregate.

Adding a new agent = write an `Agent` subclass with a unique ``role`` and import
it in ``app.multiagent.roles``. No engine code changes.
"""

from app.multiagent.base import (
    COLLABORATION_CAPABILITIES,
    Agent,
    AgentResult,
    AgentRun,
    Delegation,
    PipelineResult,
    Tool,
)
from app.multiagent.config import MultiAgentConfig
from app.multiagent.context import AgentContext
from app.multiagent.errors import (
    AgentExecutionError,
    AgentNotFoundError,
    MultiAgentError,
    PipelineError,
    ToolNotFoundError,
)
from app.multiagent.evaluation import AgentEvaluation, evaluate_run, summarize_evaluations
from app.multiagent.manager import MultiAgentManager
from app.multiagent.memory import MemorySharing
from app.multiagent.models import (
    MultiAgentEvaluation,
    MultiAgentRun,
    MultiAgentTrace,
)
from app.multiagent.registry import AgentRegistry
from app.multiagent.repository import MultiAgentRepository
from app.multiagent.schemas import (
    AgentCapabilityRead,
    AgentEvaluationRead,
    AgentResultRead,
    AgentRunRead,
    DelegationRead,
    MultiAgentCapabilities,
    MultiAgentRunDetail,
    MultiAgentRunRead,
    MultiAgentStats,
    PipelineResultRead,
    PipelineRunRequest,
    ReasoningTraceRead,
    SingleAgentRunRequest,
)
from app.multiagent.supervisor import AgentSupervisor
from app.multiagent.tool import ToolRegistry
from app.multiagent.tools import default_tools
from app.multiagent.trace import ReasoningTrace

__all__ = [
    "COLLABORATION_CAPABILITIES",
    "Agent",
    "AgentCapabilityRead",
    "AgentContext",
    "AgentEvaluation",
    "AgentEvaluationRead",
    "AgentExecutionError",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentResult",
    "AgentResultRead",
    "AgentRun",
    "AgentRunRead",
    "AgentSupervisor",
    "Delegation",
    "DelegationRead",
    "MemorySharing",
    "MultiAgentCapabilities",
    "MultiAgentConfig",
    "MultiAgentError",
    "MultiAgentEvaluation",
    "MultiAgentManager",
    "MultiAgentRepository",
    "MultiAgentRun",
    "MultiAgentRunDetail",
    "MultiAgentRunRead",
    "MultiAgentStats",
    "MultiAgentTrace",
    "PipelineError",
    "PipelineResult",
    "PipelineResultRead",
    "PipelineRunRequest",
    "ReasoningTrace",
    "ReasoningTraceRead",
    "SingleAgentRunRequest",
    "Tool",
    "ToolNotFoundError",
    "ToolRegistry",
    "default_tools",
    "evaluate_run",
    "summarize_evaluations",
]
