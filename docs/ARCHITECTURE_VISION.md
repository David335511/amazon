# Second Architecture Review — The Billion-Dollar AI Commerce Platform

**Role:** Chief Architect
**Lens:** Long-term architecture for a platform that must scale to **10M+ products, multiple SaaS tenants, ML-driven decisions, and a public developer ecosystem** — not a CRUD application.
**Constraint:** Review only. **No code changed.**
**Assumption:** The product evolves from a single internal tool into a multi-tenant platform with an SDK/plugin marketplace, forecast and AI services, and an agentic automation layer.

---

## Executive Summary

The current codebase is a **well-layered monolith** and an *excellent* proving ground. It will **not** survive a billion-dollar trajectory in its present shape, but — critically — **most of the future is an extraction problem, not a rewrite problem.** The bounded contexts, plugin abstraction, and strategy-pattern matchers already sketch the seams where services should split.

The single most important architectural decision for the next five years is this: **design the platform as a set of event-sourced, contract-first domains assembled into a modular monolith now, with explicit service boundaries that can be peeled off without rewrites.** That converts "the monolith-to-microservices death march" into "lift-and-shift a well-sealed module."

Second most important: **invest early in a Feature Store + ML Platform as the nervous system**, because every "intelligent" behavior (matching, sourcing, forecast, decision, agent) is downstream of features. It is the highest-leverage subsystem in the whole vision.

---

## 1. Domain-Driven Design — Bounded Contexts

### 1.1 Is the current module layout correct?

**Partially.** The current `app/` layout (`agent, ai, analytics, assistant, matching, plugins, profit, sourcing`) mixes **domains, capabilities, and infrastructure** in one flat namespace. That's fine for a monolith; it is *not* a set of bounded contexts.

**Correctness assessment:**

| Current module | Is it a bounded context? | Verdict |
|---|---|---|
| `products` (in `domain`) | ✅ yes | Catalog/Core — keep as its own context |
| `orders` | ✅ yes | Ordering — keep, but it will later become an event consumer |
| `plugins` | ⚠️ half | This is **Supplier Context**'s interface, not a context itself |
| `sourcing` | ⚠️ half | **Sourcing/Opportunity** — mostly right, but contains scoring+risk (should move to ML/Decision) |
| `matching` | ⚠️ half | **Matching/Identity** — mostly right, but needs a Feature Store behind it |
| `analytics` | ❌ wrong shape | **Observability** + **Historical data** conflated; it's a data/measurement context, not the source of truth for business logic |
| `profit` | ✅ mostly | Part of **Pricing/Economics** context |
| `assistant` | ⚠️ | **AI Assistant** — a product surface, not a domain; it orchestrates other contexts |
| `agent` | ⚠️ | **Agentic automation** — an orchestration layer over domains, not a domain itself |
| `ai` | ❌ wrong shape | **AI** is infrastructure/capability, not a domain; should not own business logic |
| `i18n` | ✅ | Cross-cutting, correctly separated |
| `core`, `infrastructure` | ✅ | Technical subdomains — correct to keep separate |

### 1.2 The verdict on your proposed list

> Should Products, Marketplace, Suppliers, Pricing, Inventory, Forecast, Knowledge Graph, AI, Decision, Agent become independent domains?

**Yes — but with important corrections about *what kind of thing* each is.** Three classes of bounded context exist, and treating them all the same is the classic error:

1. **Core domains** (own business state, source of truth):
   - **Catalog/Products** — split further into *Catalog (product identity/attributes)* + *Inventory (stock, multi-warehouse)*.
   - **Marketplace** — Amazon BuyBox, BSR, fees, offers. Currently buried in `analytics` + `keepa`. Promote to a real domain.
   - **Suppliers** — supplier registry + supplier product data + plugin adapters. Merge `plugins` into this.
   - **Pricing** — economics: fees, margins, break-even, repricing rules. Absorb `profit`.
   - **Forecast** — demand/sales/BSR forecasting. New.
   - **Knowledge Graph** — the relational web of brands/categories/products/competitors. New.

2. **Supporting / ML domains** (compute, no business state of their own, but own *artifacts*):
   - **Decision** — the recommendation policy (BUY/WATCH/PASS, risk thresholds). Owns decision policy + decision log.
   - **AI/Memory** — LLM orchestration + memory + embeddings. Owns prompts, model registry references, vector store.
   - **Feature Store** — features + lineages (see §3).

3. **Orchestration surfaces** (depend on domains, contain no core truth):
   - **Agent** — workflow/orchestration across domains.
   - **Assistant** — conversational surface.

### 1.3 Merges vs. splits (the honest call)

**Merge:**
- `plugins` → `Suppliers` domain (plugin = adapter of the Supplier context).
- `profit` → `Pricing` domain.
- `analytics` (business half) → split: **`Marketplace`** (external data) + **`Observability`** (metrics/tracing) + **`Data Lake/BI`** (historical warehouse). Do *not* keep one "analytics" thing — it's three different concerns.
- `ai` + `assistant`'s retrieval + agent's memory → **`AI/Memory`** supporting domain.

**Split:**
- `Products` → **Catalog** + **Inventory** (different transaction rates, different scaling: catalog is read-heavy, inventory is write-heavy).
- `sourcing` → **Sourcing/Opportunity** (business flow) + **Decision** (policy) + **Risk** (now a Feature/Ml concern).
- `matching` → **Matching/Identity** (the algorithm) + its **Feature Store** dependency.

**Suggested bounded-context map (target):**

```
                        ┌───────────────────────────────┐
                        │         AGENT (orchestration)  │
                        │         ASSISTANT (surface)    │
                        └──────────────┬────────────────┘
                                       │
     ┌────────────┬────────────┬───────┴──────┬───────────────┬───────────┐
     ▼            ▼            ▼              ▼               ▼           ▼
  Catalog     Inventory    Marketplace     Suppliers      Pricing    Forecast
     └────────────┬────────────┴──────────────┴───────────────┘           │
                  ▼                                                       │
            KNOWLEDGE GRAPH ◄───────── (product/web of relations)          │
                  ▼                                                       │
              FEATURE STORE ◄─────────────────────────────────────────────┘
                  │
                  ▼
         DECISION  ·  AI/MEMORY  ·  MATCHING/IDENTITY  (supporting/ML)
                  │
                  ▼
        DATA LAKE  ·  BI  ·  OBSERVABILITY  (data & ops)
```

---

## 2. Microservice Readiness

### 2.1 Where do service boundaries *naturally* fall?

The honest answer: **nowhere yet — and that's correct.** The system should stay a **modular monolith** until there's a concrete scaling or team-split driver. Premature microservices multiply operational debt by 10x. **Design the boundaries now; cut them later.**

Natural service boundaries (in order of *how soon they'd each make sense to peel off*):

| Service | When to extract | Driver |
|---|---|---|
| **Agent/Workflow** | **First** | Different scaling (long-running, bursty); needs its own workers; currently ephemeral |
| **Forecast ML service** | Next | Needs GPU/serving + retraining cadence unlike CRUD |
| **Matching/Identity service** | Next | CPU-heavy, cache-friendly, batchable |
| **Marketplace ingestion** | Next | External API rate limits, needs its own retry/queue |
| **Suppliers/Plugins** | Medium | Plugin sandboxing (third-party code) demands process isolation |
| **Feature Store** | Medium | High-frequency read path; needs low latency |
| **AI/Memory** | Medium | Model routing, token cost control |
| **Decision service** | Later | Pure policy — cheap to keep in monolith longest |
| **Catalog** | **Last** | The most-coupled, highest-cohesion domain; cheapest to keep together |

### 2.2 APIs between services

Adopt **contract-first, event-carried state transfer.** Each service exposes:
- **Commands/RPC** (request-response) for synchronous needs: `POST /decision/evaluate`, `POST /matching/match`, `POST /catalog/lookup`.
- **Events** (async) for propagation: `product.created`, `price.changed`, `inventory.changed`, `buybox.changed`, `opportunity.found`, `decision.created`, `forecast.ready`.

Recommended API layer per service:
- **REST/OpenAPI** for external + dashboard + admin (already present).
- **gRPC** for internal high-throughput, low-latency calls: Feature Store, Matching, Catalog lookup.
- **Message queue / event stream** for everything fan-out: Analytics, BI, Notifications, Data Lake.

### 2.3 Shared contracts

Create a **`contracts/` package** (versioned, imported by all services, never breaking):
- **Canonical DTOs** — the single `SupplierProduct`, `AmazonProduct`, `Product`, `PricePoint`, `Decision`, `Opportunity`, `Feature` types. *(Today these are duplicated in 5 modules — this is the single highest-value contract refactor.)*
- **Event schemas** — Avro or JSON-Schema for every event.
- **Error contracts** — standardized `Problem+JSON` envelope.

**Rule:** a service may depend on `contracts/` and its own internals only. This is the "anti-corruption layer" that makes later extraction non-invasive.

---

## 3. Feature Store

**Verdict: Yes — Feature Store becomes its own subsystem, and it is the most strategically important one in the entire vision.**

### 3.1 Why
Every "intelligent" behavior (Matching, Sourcing, Forecast, Decision, Agent reflection) currently computes features *ad hoc* and inline — scores, embeddings, ratios, lagged prices, BSR trends. Without a Feature Store, every new ML model re-derives features differently → **inconsistent, unversioned, unlineageable, and impossible to serve online vs. train offline from the same source.**

### 3.2 Feature generation
- **Batch** (offline): compute daily/hourly feature tables from the Data Lake (Spark/Flink or DuckDB/ClickHouse jobs).
- **Streaming** (online): compute on write of `price.changed`/`inventory.changed` events.
- **On-demand** (serving): compute for a single request with caching.
- Central **Feature Registry** defines each feature once (name, type, computation, owner).

### 3.3 Feature versioning
- Each feature has an immutable version. Models pin feature versions.
- Backfill = recompute historical values for a version.
- **No mutable in-place updates** — append + version + point-in-time lookup.

### 3.4 Feature lineage
- Every feature records: **source tables/events → transformation code (git SHA) → feature version → which models consume it.**
- Enables answering: *"If I change how 'price momentum' is computed, which models retrain, and what do I need to re-backfill?"* — this is the thing that saves multi-week incident investigations at scale.

### 3.5 Offline vs. online features
- **Offline:** wide feature tables in the Data Lake for training; **point-in-time joins** to prevent leakage (no future data seen during training).
- **Online:** low-latency key-value store (Redis/feature DB) for serving the *same* features.
- **Guarantee:** the online and offline pipelines are generated from the *same* registry spec → parity (the hard-won lesson of every real ML platform).

### 3.6 Future ML architecture
```
Events ──► Feature Generator (batch+stream) ──► Feature Registry
                                                    │
                    Offline: Data Lake feature tables ─┤
                    Online:  Redis feature store      ─┴─► ML models (forecast, matching, decision, scoring)
                                                              │
                                                              └► Evaluation + Model Registry → serving
```

---

## 4. Knowledge Graph

### 4.1 Should graph data stay relational?
**Stay relational for the core transactional truth** (Postgres is the system of record for catalog/marketplace). But the **relationships themselves** — brand↔category↔product↔competitor↔feature-affinity — are a *graph-shaped* workload that Postgres handles with painful recursive joins.

**Two-tier recommendation:**
1. **Postgres** = authoritative source (keep it).
2. **A graph database as a derived/query-optimized layer** for traversal-heavy reads: "show me all competitors of products in category X sharing brand Y and similar price bands."

### 4.2 Would Neo4j (or another graph DB) help?
- **Yes, eventually — for specific read patterns only**, not as the source of truth.
- **Neo4j**: richest ecosystem, Cypher, plugins. Best if you want recommendation + competitive graph products out of the box.
- **Alternative — the pragmatic pick: start with a **relational-adjacent approach** using Postgres **recursive CTEs + adjacency/closure tables + GIN indexes**, or **EdgeDB/Apache AGE** (graph extension over Postgres), before committing to a separate engine. For 10M nodes, Postgres recursive CTEs are fine; for *billion-node traversals*, Neo4j/Jena-style engines win.
- **Cheapest middle path:** keep the graph in Postgres now; model edges as a table; *reserve* the abstraction behind a `KnowledgeGraph` engine interface so Neo4j can be swapped in without touching callers.

### 4.3 Migration strategy (Postgres → graph DB)
```
Phase A: Model edges as tables in Postgres; write a KnowledgeGraph engine behind an interface.
Phase B: Build an ETL that snapshots the relational graph → Neo4j (or AGE) nightly.
Phase C: Route traversal-heavy reads to the graph DB; keep Postgres authoritative; add reverse-sync on graph write.
Phase D: If/when scale demands, graph DB becomes serving source for traversal; Postgres stays the transactional ledger.
```
Key rule: **the graph DB is a query accelerator and derived index, never a second source of truth** (avoid the dual-write consistency nightmare).

---

## 5. Machine Learning Platform

### 5.1 Should forecasting be an independent ML service?
**Yes.** Forecasting (demand, sales, BSR) is the canonical ML workload: distinct train/serve cadence, retraining on new data, model versions, accuracy evaluation, and it's the highest-value prediction for a commerce platform. It should be a **dedicated Forecast Service** with its own lifecycle, independent of the CRUD monolith.

### 5.2 The Forecast Service architecture
- **Training:** scheduled retraining (daily/weekly) reading features from the Feature Store + Data Lake. Candidate models: statistical baselines (Holt-Winters, Prophet) + gradient boosting + (later) deep models. Train **many** and pick via validation.
- **Serving:** low-latency inference endpoint; caching; fallback to baseline if model fails.
- **Feature generation:** consumed from the Feature Store (not ad hoc).
- **Evaluation:** holdout, backtesting, **forecast accuracy tracking** per product/sku/category (MAPE/WAPE) — logged as a business metric (§9).
- **Model registry:** every trained model logged with metrics, features used, training data snapshot, artifact. **No model is served without registry metadata.**
- **A/B deployment:** traffic-split old vs. new model; shadow-deploy new models; promote only on measured accuracy improvement; instant rollback.

### 5.3 Platform-level ML architecture (all models)
One unified ML Platform for forecast + matching + decision + scoring:
```
Feature Store ──► Training (batch) ──► Model Registry (metrics, lineage, artifacts)
                     │                          │
                     └── evaluation/backtest ───┤
                                                ▼
                                     Serving (online inference, A/B, shadow)
                                                │
                                     Monitoring: accuracy, drift, latency, token cost
```

---

## 6. Vector Search & AI Memory

### 6.1 Verdict
The `assistant/retriever.py` and `ai/` layer are a good start, but **AI Memory needs to be a first-class subsystem** with proper embedding storage and retrieval — today memory is ephemeral and unversioned.

### 6.2 Embedding storage & vector database
- **Embedding storage:** derive embeddings in the Feature Store pipeline; store both the vector and its source text hash + metadata.
- **Vector DB options:**
  - **Start:** **pgvector** on Postgres (you already run Postgres — zero new infra, good to ~10M vectors).
  - **Scale:** **Qdrant** or **Milvus** (or managed Pinecone) when beyond ~50–100M vectors or when you need high-QPS ANN search.
  - **Decision:** put vector search behind a `VectorStore` interface so pgvector→Qdrant is a swap, not a rewrite.

### 6.3 Retrieval strategy
- **Hybrid search (recommended):** combine **BM25/keyword** + **dense vector** + **metadata filters**, reranked (cross-encoder or score fusion). Keyword+vector+metadata is the production standard; don't rely on pure embeddings.
- **RAG pipeline:** retrieve → rerank → context window assembly → LLM → answer with citations.

### 6.4 Chunking
- Domain-aware chunking: chunk by product record, decision record, competitor narrative, supplier note — **not** naive fixed tokens. Preserve metadata (product_id, asin, timestamps, source, confidence) on every chunk for filtering and provenance.

### 6.5 Memory expiration
- **Hierarchical memory:** (a) **ephemeral** working memory (session, TTL hours); (b) **semantic** long-term memory (facts, decisions, learned preferences); (c) **procedural** (how-to/tool usage).
- **Expiration policy:** TTL per memory class; **consolidation** (summarize old memories into higher-level facts — the "reflection" step, §8); retention aligned with data policy.

### 6.6 Hybrid search architecture
```
Queries ──► Query rewrite/expansion
               ├─► BM25 (keyword) ─────┐
               ├─► Dense embedding ────┼─► Fusion + Rerank ─► Context ─► LLM
               └─► Metadata filters ───┘
Vectors in pgvector/Qdrant · text in Postgres/Docstore · both behind VectorStore interface
```

---

## 7. Workflow Engine

### 7.1 Verdict
The **agent scheduler is a home-grown, in-memory, single-process workflow engine.** For a long-running, multi-step, durable, resumable workflow (scan → gather → evaluate → decide → notify → forecast) this will not scale. **Introduce a real workflow engine.**

### 7.2 Options & tradeoffs

| Engine | Fit | Pros | Cons | Verdict |
|---|---|---|---|---|
| **Temporal** | **Best** | Durable execution, retries, timers, human-in-the-loop, visibility, scales horizontally | New infra (server + workers); learning curve | **Recommended long-term** |
| **Prefect** | Good for data/ML pipelines | Python-native, DAGs, scheduling | Less suited to long-running agentic control flows & human steps | Good for Data Lake/feature jobs |
| **Airflow** | Good for batch/ETL | Mature, scheduler | Not for real-time/stateful workflows; heavy | Use for **batch/Data Lake only** |
| **Dagster** | Good for data & ML orchestration | Asset/lineage-first, great for Data Lake + Feature Store | Not for interactive agent control flows | Strong for the **ML/data** side |
| **Remain internal** | Fallback | Zero infra | Reinventing durable execution; the current in-memory state is the core weakness | Only short-term |

### 7.3 Recommended split
- **Agentic/domain workflows** (scan→decide→notify, human approval gates) → **Temporal**.
- **Data/ML pipelines** (feature generation, forecast retraining, Data Lake ingestion) → **Prefect or Dagster**.
- This is the industry-standard pairing: **Temporal for the operational flow, a data orchestrator for the data/ML flow.**

---

## 8. Agent Architecture

### 8.1 Should the current agent evolve into Planner/Executor/Research/Risk/Negotiation/Reporting/Memory/Reflection?

**Yes — but with discipline.** The current `scheduler → workers → pipeline` model is a single generic worker loop. The long-term target is a **role-specialized multi-agent system**:

| Role | Responsibility | State |
|---|---|---|
| **Planner** | Break goals into steps; orchestrate | transient |
| **Executor** | Run steps (scan, lookup, price) against domains | transient |
| **Research** | Gather competitive/context data; RAG | semantic memory |
| **Risk** | Assess risk of each decision (uses Risk model + features) | policy |
| **Negotiation** | Supplier/marketplace interaction (future — repricing, offers) | episodic |
| **Reporting** | Compose findings/summaries for humans | output |
| **Memory** | Store/retrieve episodic+semantic+procedural memories (§6) | memory store |
| **Reflection** | Post-action review: consolidate memories, improve prompts/policy | reflection log |

### 8.2 Optimal multi-agent communication
- **Do NOT let agents talk to each other arbitrarily** (the "agent soup" anti-pattern — unpredictable, unobservable, expensive).
- **Use structured messages on the workflow engine (Temporal):** Planner emits typed steps; each role is a durable activity/worker; outcomes are events. **Shared blackboard = the Feature Store + Memory + Knowledge Graph.**
- **Pattern: orchestrator-worker + pipeline + state machine.** Planner is the orchestrator; Executor/Research/etc. are workers; the overall lifecycle is a Temporal workflow (durable, resumable, observable).
- **Every agent action is audited** (decision log, event stream) — non-negotiable for a commerce platform with real money.

---

## 9. Observability

### 9.1 Verdict
Telemetry exists (OpenTelemetry optional) but is **developer-centric**. For a commerce/ML platform you need **four observability planes.**

### 9.2 Recommended planes

**A. Technical observability**
- **Metrics:** latency percentiles (p50/p95/p99), error rates, saturation, DB/Redis pool, queue depths. (Prometheus + Grafana; you already touch Grafana Cloud.)
- **Distributed tracing:** OpenTelemetry across all services (start now — retrofitting is painful). Trace request → engine → provider → DB → event → worker.

**B. Business metrics (the ones the CEO watches)**
- Products sourced, opportunities found, decision outcomes (BUY/WATCH/PASS), conversion, gross margin, avg. price advantage, inventory turns, catalog growth, daily active users, ARR per tenant.

**C. Cost & AI tracking**
- **Cost tracking:** cost per product, per forecast, per tenant; infra cost allocation (needed for §10).
- **AI token tracking:** tokens in/out, cost, latency, provider, model per request — **essential** (LLM spend is a top-3 platform cost).
- **Supplier latency:** timeouts, failure rates, mean latency per supplier (drives plugin SLAs and caching).
- **Forecast accuracy:** MAPE/WAPE per product/sku/category over time.
- **Decision accuracy:** what % of decisions were correct in hindsight (the feedback loop that closes the ML flywheel).

**Recommendation:** build a **Business Metrics service** (domain events → metric events → dashboard), separate from technical Prometheus. Both feed Grafana; business metrics also feed the BI warehouse (§12).

---

## 10. Cost Optimization

### 10.1 Operating cost estimates (Postgres/Redis on managed cloud, ~2026 ballpark)

| Scale | Products | Est. monthly infra | Notes |
|---|---|---|---|
| **10K** | 10K | **$150–300** | single PG, small Redis, free-tier compute |
| **100K** | 100K | **$800–1.5K** | larger PG + replicas, partitioning starts, moderate compute |
| **1M** | 1M | **$5K–15K** | partitioned DB, read replicas, 3–6 microservices, vector DB, cache cluster |
| **10M** | 10M | **$30K–80K+** | multi-node, data lake, ML training (GPU for deep forecast), multiple tenants |

*These exclude LLM inference cost, which scales with usage — a separate, controllable line item (see below).*

### 10.2 Optimization levers
1. **LLM cost control (biggest lever):** route to cheapest sufficient model; cache embeddings & completions; hybrid search to cut tokens; batch; use local models for high-volume/low-stakes tasks (§14). LLM budget should be a *rate-limited, per-tenant, per-call* quota.
2. **Storage tiering:** hot data in Postgres; cold/archived to **object storage + Parquet** (§11) → big win on managed DB bills.
3. **Time-series partitioning + retention:** don't pay to store 5-year-old 5-minute price points in your hot OLTP DB.
4. **Serverless/warm:** keep free-tier-friendly while small (Render); move steady-state workloads to managed services at scale but avoid over-provisioning.
5. **Cache aggressively** on matching/catalog reads (read-heavy: 10–20x read:write).
6. **Right-size & autoscale** workers (agent/forecast burst only when needed).
7. **Per-tenant cost allocation** (for SaaS) — tag every metric with tenant to charge back.

---

## 11. Data Lake

### 11.1 Should historical data stay only in PostgreSQL?
**No.** Postgres is the system of record (correct), but it is the wrong place for *historical analytics at scale*. Keep a **write-ahead append** of domain events and a **cold historical store** separately.

### 11.2 Evolution path (pragmatic, no big-bang)

```
Phase 1 (now): Postgres + archive tables. Export old time-series to Parquet files on object storage (S3/R2/MinIO). Cost: near-zero.
Phase 2: Add DuckDB (single-file, SQL, reads Parquet directly) for ad-hoc analytics without infra.
Phase 3: ClickHouse as an analytics/OLAP store for high-QPS dashboards & forecasting reads (columnar, fast, cheap at scale).
Phase 4: Iceberg table format over object storage for a true open Data Lake (time travel, ACID, schema evolution) with Spark/Flink or DuckDB reading it.
```

| Store | Role | When |
|---|---|---|
| **Parquet + Object Storage** | cold archive, cheap, open | now–Phase 1 |
| **DuckDB** | ad-hoc analytics on the lake, zero infra | Phase 2 |
| **ClickHouse** | OLAP serving for dashboards/forecast | Phase 3 |
| **Iceberg** | open-format data lake, time-travel | Phase 4 |
| **Postgres** | system of record, transactional truth | always |

**Event sourcing synergy:** the domain event stream (`product.*`, `price.*`, `decision.*`) is the natural input to the Data Lake → **a true event-carried state store.** This unifies Data Lake, BI, and Feature Store on one source of truth: the event log.

---

## 12. Business Intelligence

### 12.1 Should a dedicated analytics warehouse exist?
**Yes — a lightweight one, later.** Do *not* build a warehouse now (overkill at 10K products). But architect for it.

- **Now:** business metrics → Postgres tables + Grafana + DuckDB over Parquet exports.
- **Phase 3+:** a dedicated **OLAP warehouse** (ClickHouse for serving + Iceberg lake for history) with an **open semantic layer** (dbt-style models defining metrics like *margin, ARR, forecast accuracy*).
- **Key rule:** **BI reads the event log / warehouse, never the OLTP database directly** — protects the transactional system and gives one governed source of truth for reports.
- This BI plane is what makes the platform **SaaS-ready** (per-tenant analytics, usage, billing).

---

## 13. API Versioning & External API Strategy

### 13.1 Verdict
**REST is the right external default; GraphQL for a public developer portal query surface; gRPC for internal service-to-service; WebSockets for live dashboards; event streaming for data delivery.**

| Style | Role | Where |
|---|---|---|
| **REST/OpenAPI** | primary external API | all public + dashboard (keep; version it) |
| **GraphQL** | developer-facing query surface | public developer portal, flexible field selection |
| **gRPC** | internal high-throughput | Feature Store, Matching, Catalog lookup |
| **WebSockets** | live/streaming UI | dashboard real-time, agent progress |
| **Event streaming (Kafka/Redpanda/NATS)** | data delivery, integrations, Data Lake | all domain events |

### 13.2 Long-term API strategy
- **Version by URL (`/api/v1`, `/api/v2`) for breaking changes; additive changes are backwards-compatible.**
- **Contract-first:** schemas (OpenAPI/JSON-Schema/Protobuf) are the source of truth, generated in the `contracts/` package.
- **Public SDK** wraps the REST + GraphQL + streaming APIs so external developers don't touch internals (§15).
- **Webhook + event subscription** as the integration pattern for partners (push, not poll).
- **Rate limits, API keys, OAuth, usage metering** from day one of going public (you already need auth for internal security).

---

## 14. Offline AI

### 14.1 How should local LLMs (Ollama, vLLM, LM Studio) integrate?
**As first-class providers behind the existing `LLMProvider` abstraction — which is already the right shape** (`ai/base.py` ABC + `ai/providers/`). Today only Anthropic/OpenAI/Ollama exist; the abstraction is correct.

### 14.2 Recommended abstraction
```
LLMProvider (ABC: generate, is_available, cost, model_id)
   ├─ Remote: AnthropicProvider, OpenAIProvider
   ├─ Local:  OllamaProvider, vLLMProvider (OpenAI-compatible), LMStudioProvider
   └─ Router: ModelRouter (cost/latency/capability-aware)
```
- **ModelRouter** selects provider per task: high-stakes reasoning → flagship remote; high-volume/low-stakes → local (vLLM/Ollama) or cheap model.
- **Unified interface:** all providers expose `generate` + `cost` + `latency` + `token` telemetry so the platform can optimize spend (§9, §10) and fail over (local if remote down, and vice-versa).
- **Abstraction rule:** business logic never knows the provider — it only calls the router. This makes local/offline LLMs a *deployment and cost* decision, not a code change.

---

## 15. Extensibility & the Public SDK

### 15.1 How can external developers build plugins?
The **plugin system is already the right mental model** (`BaseSupplierPlugin` ABC + registry + manager) — extend this pattern to *every* provider family and expose it as a **public SDK.**

### 15.2 The target: a `platform-sdk` package
External devs implement a small ABC per extension point and publish:

| Extension point | Contract (ABC) | Model (like) |
|---|---|---|
| **Marketplace plugins** | `BaseMarketplaceAdapter` | marketplace data (BuyBox, BSR, offers) |
| **Supplier plugins** | `BaseSupplierPlugin` (exists!) | search/lookup/pricing/inventory/shipping/coupon/availability |
| **Forecast providers** | `BaseForecastProvider` | produce forecasts; platform owns registry/eval |
| **Notification providers** | `BaseNotifier` | push/email/SMS/webhook |
| **AI providers** | `LLMProvider` (exists!) | generate + cost + telemetry |
| **Decision providers** | `BaseDecisionProvider` | propose BUY/WATCH/PASS with confidence |

**Architecture of the SDK:**
- **Sandboxing:** third-party plugins run in **isolated processes/containers** (or WASM) with rate limits, timeouts, resource caps, and secret-scoped config. This is *why* the Supplier context becomes its own service — to isolate untrusted code.
- **Versioned contracts** in `contracts/`; SDK pins them.
- **Certification/rating** + a **plugin marketplace** (discovery, install, per-tenant enablement, usage metering) → a genuine **platform business model** (the "billion-dollar" lever: you're not just a tool, you're a marketplace).
- **Revenue paths:** SaaS per-tenant, plugin marketplace commissions, usage-based forecast/AI services.

---

## Deliverables

### Architecture Score
**Current architecture (as a monolith): 62/100**
**Target architecture (bounded contexts + contracts + event-driven): 82/100** — achievable without a rewrite by sealing the seams in §1–§2.

### Future Scale Score — **55/100**
Strong foundation and correct seams, but blocked by: no event bus, in-memory agent state, unpartitioned time-series, no feature store, no real workflow engine.

### AI Readiness Score — **40/100**
Good `LLMProvider` abstraction, but AI is not yet a coherent subsystem: no memory, no model router, no token-cost telemetry, no prompt versioning, decision/risk logic not ML-first.

### SaaS Readiness Score — **35/100**
No multi-tenancy, no auth/tenants/billing/usage metering/rate limits. The biggest *capability* gap in the whole vision. (Start with auth + tenant IDs + per-tenant metrics.)

### ML Readiness Score — **30/100**
No Feature Store, model registry, training pipeline, evaluation, or A/B. Forecast/scoring are ad hoc. This is the highest-leverage greenfield investment.

### Microservice Readiness Score — **60/100**
Bounded contexts and the plugin/matcher patterns are right; but no contract package, no service boundaries yet drawn in code, single-process scheduler. Ready to *begin* sealing seams, not to split yet.

---

## Top 20 Long-Term Improvements (ranked)

1. **Build the `contracts/` package** — canonical DTOs + event schemas (kills the 5-way duplication; unlocks everything). *(1–2 wk)*
2. **Add authentication + multi-tenant isolation** (auth, tenant scoping, RBAC). *(3–4 wk)*
3. **Introduce a domain event bus** (in-process now, Kafka-ready interface) — event-carried state. *(3 wk)*
4. **Create a Feature Store** (registry + batch/online/on-demand features + lineage). *(4–6 wk)*
5. **Introduce Temporal (or Prefect)** for durable workflows; make agent state durable & auto-starting. *(3–4 wk)*
6. **Make the AI layer a coherent subsystem:** ModelRouter, memory (hierarchical), token-cost telemetry, prompt versioning. *(3–4 wk)*
7. **Split the god classes** (AnalyticsService/Repo, sourcing/engine, domain/models/sourcing). *(2–3 wk)*
8. **Promote Marketplace + Pricing + Inventory as real domains**; absorb `plugins`/`profit`; separate `analytics` into Marketplace/Observability/Data. *(3 wk)*
9. **Wire engines via DI; remove inline construction + cross-module repo imports.** *(1–2 wk)*
10. **Build a Forecast Service** with model registry, evaluation, A/B, fallback baselines. *(4–6 wk)*
11. **Introduce pgvector for vector search behind a `VectorStore` interface**; hybrid retrieval (BM25+dense+filters). *(2 wk)*
12. **Set up four-plane observability:** OTel tracing, Prometheus/Grafana, business metrics service, AI/cost tracking. *(2–3 wk)*
13. **Data Lake Phase 1:** event log + Parquet archive on object storage. *(1–2 wk)*
14. **Time-series partitioning + retention + composite indexes.** *(1–2 wk)*
15. **Parallelize + cache** (cross-supplier `asyncio.gather`, Redis caching, embedding batch). *(1–2 wk)*
16. **Decision & Risk as ML-first engines** consuming features, with a decision-accuracy feedback loop. *(3 wk)*
17. **Public SDK (`platform-sdk`)** with certified plugin marketplace + sandboxing. *(5–8 wk)*
18. **ClickHouse OLAP store + semantic BI layer** (dbt-style metrics). *(3–4 wk)*
19. **Graph layer (Postgres edges → Neo4j/AGE) behind a KnowledgeGraph interface.** *(2–3 wk)*
20. **Per-tenant cost allocation + LLM budget/quota enforcement.** *(1–2 wk)*

---

## Five-Year Architecture Roadmap

**Year 1 — Foundations & Security**
- Auth + multi-tenancy; `contracts/` package; event bus; DI cleanup; god-class splits; canonical DTOs; OTel tracing + Grafana.

**Year 2 — The ML & Data Nervous System**
- Feature Store (registry, offline/online, lineage); Forecast service (registry + eval + A/B); pgvector + hybrid retrieval; AI memory; business metrics + AI/cost tracking; Data Lake Phase 1 (Parquet).

**Year 3 — Scale the Runtime**
- Durable workflows (Temporal); agent becomes role-specialized multi-agent; parallelize + cache; time-series partitioning + ClickHouse OLAP; first services peel off (Agent, Forecast, Matching); modular monolith → first real service boundaries.

**Year 4 — Productize as a Platform**
- Public `platform-sdk`; plugin marketplace + sandboxing; GraphQL portal; event streaming (Kafka) for partners; SaaS billing/usage; graph layer for competitive insights.

**Year 5 — Platform Flywheel**
- Decision-accuracy feedback loop matures; self-improving agents (reflection); full event-sourced Data Lake (Iceberg); BI warehouse self-serve; multi-region; 1M+ products on a truly multi-tenant, ML-native platform.

---

## Ten-Year Architecture Vision

By year ten, the platform is **not "an app" but a platform fabric**:

- **A core of trusted domains** (Catalog, Inventory, Marketplace, Suppliers, Pricing, Forecast) as durable, contract-first services — thin, correct, stable.
- **A data spine:** one event log (event-carried state) feeding an open Data Lake (Iceberg), a Feature Store, an OLAP warehouse, and BI — **single source of truth, no fragile pipelines.**
- **A machine brain:** Feature Store + model registry + serving + A/B + drift monitoring + decision-accuracy feedback. ML is *the* product, not an add-on: forecasting, pricing, matching, sourcing scoring, and risk all train, evaluate, and improve continuously.
- **An agentic layer:** a governed multi-agent system (Planner/Executor/Research/Risk/Negotiation/Reporting/Memory/Reflection) running on durable workflows — automating the full commerce loop (source → price → forecast → decide → list → monitor → optimize), self-improving via reflection, and auditable end-to-end.
- **A marketplace:** a certified public ecosystem (supplier/marketplace/forecast/notification/AI/decision plugins) that is itself a revenue line — the platform is a *fabric others build on*, not a tool they use.
- **A SaaS business** with per-tenant isolation, usage metering, cost allocation, and self-serve BI.

**The defining principle:** *today's well-layered monolith is a proving ground. Seal the seams (contracts + event bus), grow the ML/data nervous system, and the platform accretes capabilities without rewriting — turning a good CRUD app into the operational fabric of a billion-dollar AI commerce company.*

---

*Report written to `docs/ARCHITECTURE_VISION.md`. No code changed.*
