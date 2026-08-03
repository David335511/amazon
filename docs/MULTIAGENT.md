# Multi-Agent Orchestration Framework

A pluggable, collaborative set of specialist agents that work together on a
sourcing / fulfilment task. Built on the platform's existing engines (reverse
sourcing, forecasting, supplier intelligence, finance) — each surfaced to agents
as a **tool**.

## The ten specialist agents

| Agent       | Role        | Responsibility                                                        | Depends on                       |
|-------------|-------------|-----------------------------------------------------------------------|----------------------------------|
| Planner     | `planner`   | Supervises & decomposes the task; decides who runs and in what order. | — (runs first)                   |
| Research    | `research`  | Gathers supplier offers + product intel for an ASIN.                  | —                                |
| Matching    | `matching`  | Ranks offers by landed cost, honours constraints.                     | research                         |
| Forecast    | `forecast`  | Forecasts demand.                                                     | research                         |
| Pricing     | `pricing`   | Recommends a selling price from cost + target margin.                 | matching, forecast               |
| Profit      | `profit`    | Estimates margin, ROI and total profit.                               | pricing, matching, forecast      |
| Risk        | `risk`      | Assesses sourcing risk (reliability, shipping, demand, margin).       | matching, profit, forecast       |
| Negotiation | `negotiation` | Builds a negotiation strategy (discount, MOQ, tactics).             | matching, profit                 |
| Inventory   | `inventory` | Recommends reorder quantities / stock levels.                         | forecast, profit                 |
| Reporting   | `reporting` | Consolidates all findings into a report + executive summary.          | everything                       |

## Collaboration capabilities

- **Task delegation** — an agent hands a subtask to another via the shared
  registry: `await context.delegate("research", {"asin": ...})`. The result is
  recorded on the run and written to shared memory (`delegation:<role>`).
- **Memory sharing** — every agent reads/writes the same `AgentContext`
  (`context.share` / `context.recall`). An optional `MemorySharing` backend
  persists key insights to the AI memory system.
- **Reasoning traces** — agents call `context.trace(step, detail, **data)`; the
  full deliberation is persisted per run and exposed over the API (replayable).
- **Tool usage** — agents call `await context.use_tool(name, **kwargs)`.
  Pure-math tools (`landed_cost`, `markup`) are always available; engine tools
  (`reverse_source`, `supplier_scores`) are wired through DI.
- **Parallel execution** — the supervisor orders agents by `depends_on` into a
  DAG and runs independent agents concurrently (`asyncio.gather`). The pipeline
  finishes in waves, not serially.
- **Agent supervision** — the Planner runs first; the supervisor monitors every
  agent, isolates failures (a failed agent degrades the run, never crashes it)
  and reports a single aggregate status.
- **Agent evaluation** — every agent run gets a 0..1 score weighting success
  (0.5), confidence (0.2) and output completeness (0.3); per-role stats are
  aggregated for the operator.

## Adding a new agent (zero engine changes)

Write a subclass of `Agent` with a unique `role` and import it in
`app/multiagent/roles/__init__.py`:

```python
from app.multiagent.base import Agent, AgentResult

class ComplianceAgent(Agent):
    role = "compliance"
    display_name = "Compliance Agent"
    description = "Checks a sourcing decision against compliance rules."
    capabilities = ["compliance"]
    default_tools = ["compliance_rules"]
    depends_on = ["matching", "negotiation"]   # drives parallel-wave ordering

    async def run(self, context):
        # read shared memory, use tools, delegate, trace ...
        return AgentResult(role=self.role, summary="...", data={...},
                           recommendations=[...], confidence=0.8)
```

The supervisor, memory, delegation, evaluation and API all discover it
automatically. No engine code changes.

## API

| Method | Path                                | Purpose                          |
|--------|-------------------------------------|----------------------------------|
| GET    | `/api/v1/multiagent/capabilities`   | Registered agents + capabilities |
| GET    | `/api/v1/multiagent/agents`         | Discover the agents              |
| POST   | `/api/v1/multiagent/pipeline`       | Run a supervised pipeline        |
| POST   | `/api/v1/multiagent/agents/{role}/run` | Run one agent in isolation   |
| GET    | `/api/v1/multiagent/runs`           | List stored runs                 |
| GET    | `/api/v1/multiagent/runs/{id}`      | Run + traces + evaluations       |
| GET    | `/api/v1/multiagent/runs/{id}/traces` | Reasoning traces              |
| GET    | `/api/v1/multiagent/evaluations`    | Agent evaluations                |
| GET    | `/api/v1/multiagent/stats`          | Aggregate stats + per-role eval  |

**Pipeline request:**

```json
{
  "task": {
    "asin": "B0TEST001",
    "action": "source",
    "quantity": 100,
    "target_margin": 0.30,
    "seed": { "supplier_offers": [ { "supplier": "walmart", "unit_price": 10.0, ... } ] }
  },
  "roles": null
}
```

`roles: null` runs the default set (all ten, planner first). `seed` injects
known data so agents work even with no supplier plugins configured; the
`reverse_source` tool overrides it when enabled.

## Storage

- `multiagent_runs` — one row per pipeline (task, status, summary, shared-memory
  snapshot, timing).
- `multiagent_traces` — per-agent reasoning steps (replayable).
- `multiagent_evaluations` — per-agent quality metrics.

Run ids cascade, so deleting a run removes its traces and evaluations.
