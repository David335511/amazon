# Architecture Review — Amazon AI Commerce Platform

**Role:** Principal Engineer pre-release review
**Scope:** Whole codebase (`app/`, migrations, config, tests)
**Constraint honored:** Review only — **no code changes made.**
**Date:** 2026-08-02

---

## 1. Architecture Score

**62 / 100** — "Solid foundation, not yet production-scale."

The skeleton is genuinely well-designed (clean layering, plugin abstraction, FastAPI factory, strategy-pattern matchers, pure profit engine). But it collapses at the *edges*: there is **no authentication**, **no event-driven decoupling**, and several **god classes** that will become the bottleneck the moment the platform grows past tens of thousands of records or multiple consumers.

**Production Readiness Score: 45 / 100** — see §11.

---

## 2. Strengths (what to keep)

1. **Discipline of the 5-layer vertical flow.** `API → Schema → Service → Repository → Model` is followed consistently in the core domain (products, orders). Routes are thin; schemas validate; services hold rules; repositories own SQL. This is the right shape to build on.
2. **Factory app + lifespan resource management** (`app/main.py`). Clean startup/shutdown of DB pool, Redis, telemetry, schedulers. Testable (multiple app instances).
3. **Plugin abstraction is genuinely good** (`app/plugins/base.py`, `registry.py`, `manager.py`). A single 8-method ABC, standardized Pydantic output models, shared HTTP client, error isolation across suppliers. This is the template other provider families (marketplace, forecast, notification) should follow.
4. **Strategy-pattern matching** (`app/matching/engine.py` + `matchers.py`). Plug-in matchers (barcode, brand/title, fuzzy, spec, image, embedding) behind a `BaseMatcher` ABC with a scoring/confidence engine. Clean, extensible.
5. **Focused pure engines.** `ProfitEngine` is a well-isolated, deterministic, unit-testable computation engine with a proper `ProfitConfig`. This is the model other engines should imitate.
6. **Repository pattern + generic `BaseRepository`.** Centralizes CRUD, enables SQLite swaps in tests.
7. **Good hygiene:** `from __future__ import annotations`, typed signatures, docstrings, module docstrings stating *design decisions*, centralized config layering (YAML + env), global exception-handler mapping, Alembic migrations, 249 passing tests.

---

## 3. Weaknesses (headline)

1. **No authentication or authorization anywhere** (CRITICAL). Every `/api/v1/*` route and the dashboard are publicly reachable and unauthenticated. See §13.
2. **No event bus.** Every workflow is synchronous, direct-call fan-out. The agent pipeline and analytics do heavy work inline. No `PriceChanged`/`DecisionCreated`-style decoupling. See §8.
3. **God classes.** `AnalyticsService` (773 LOC), `AnalyticsRepository` (700), `sourcing/engine.py` (621), `domain/models/sourcing.py` (751, many models in one file), `seed_data.py` (576). These mix multiple responsibilities.
4. **Duplicate models/DTOs/logic.** The "supplier product" concept is redefined in ≥5 places; `_parse_json_response` duplicated; a second logger exists. See §7.
5. **Tight coupling via direct construction, not DI.** `SourcingEngine` instantiates `ProfitEngine` inline and imports `AnalyticsRepository` directly; a module-level `_get_ai_reasoning()` factory creates the AI engine lazily. Hard to mock, hard to test in isolation, breaks the "repositories never talk to other repositories" rule.
6. **Agent is ephemeral & not auto-started.** Worker state lives in process memory; a redeploy/restart kills it; it isn't started on boot. Combined with blocking Redis reads that time out on Upstash free, it is not reliable 24/7.
7. **CORS misconfiguration:** `allow_origins=["*"]` with `allow_credentials=True` — an invalid/insecure combination (browsers reject it; credentials+wildcard is a hazard).
8. **Performance ceilings** — no caching of expensive results, sequential cross-supplier calls (no `asyncio.gather`), embedding matching calls an external LLM per candidate, time-series queries unpartitioned.

---

## 4. Refactoring Recommendations (by theme)

### A. Decoupling & DI (High)
- **Inject engines via dependencies**, never construct inside other engines. Add a `Container` (already exists) method per engine: `profit_engine()`, `sourcing_engine()`, `ai_reasoning_engine()`, `matching_engine()`. Remove `_get_ai_reasoning()` module-level factory; inject `AIReasoningEngine` into `SourcingEngine`.
- **Stop importing another module's repository.** `SourcingEngine → AnalyticsRepository` is a cross-module reach. Give sourcing its own read model/query service, or route through a domain service.

### B. Introduce an event bus (High)
- Add a lightweight in-process async event bus (publish/subscribe) — start in-memory, keep an interface so Redis/RabbitMQ can back it later. Emit domain events (`PriceChanged`, `InventoryChanged`, `BuyBoxChanged`, `OpportunityFound`, `DecisionCreated`, `NotificationSent`) and let analytics/notifications subscribe instead of being invoked inline.

### C. Break up god classes (High)
- **`AnalyticsService`**: split into `AnalyticsCollector` (ingest) and `AnalyticsQuery`/summary (read). Or make ingest an event handler and read a separate service.
- **`AnalyticsRepository`**: split into per-metric repositories (PriceRepo, InventoryRepo, FeeRepo) or a single time-series repository with narrower methods.
- **`sourcing/engine.py`**: extract risk scoring → `RiskEngine`, opportunity scoring → `ScoringEngine` (there is already `sourcing/scoring.py` — consolidate), summary/recommendation text → a `ReasoningEngine`.
- **`domain/models/sourcing.py`**: split into per-aggregate model modules (`supplier.py`, `supplier_product.py`, `product_price.py`, `decision.py`, …).

### D. Kill duplication (Medium)
- **One canonical supplier-product DTO.** Define `SupplierProduct` once (e.g. in `app/domain/schemas/sourcing.py`); have `plugins`, `matching`, `agent`, `assistant` import it. Provide mappers from plugin output → canonical.
- **One JSON-parse helper** in a shared util (`app/core/json.py`) for `_parse_json_response` (ai/reasoning + assistant).
- **One logger**: delete `app/agent/logger.py`, use `app/core/logging.get_logger`.
- **One money helper**: centralize `_money`/Decimal normalization.
- **DRY the cross-supplier bulk ops** in `PluginManager` (search_all / lookup_all / compare_pricing share the same loop) into a single parameterized helper, and parallelize with `asyncio.gather`.

### E. Persistence & life-cycle of the agent (High)
- Make agent run state durable (heartbeats already exist → persist a "desired state" so it auto-restarts), and **auto-start on boot** behind a config flag (`features.agent: true`).
- Replace blocking `BRPOP` with **polling or non-blocking** dequeue to avoid Upstash-free timeouts; keep a retry/backoff.

### F. Engines you should create (see §6)

---

## 5. Updated Layer Diagram (target state)

```
            ┌────────────────────────────────────────────────────────┐
            │                     API  (app/api/v1)                  │
            │        AuthZ  RateLimit  Validation  Schemas           │
            └───────────────┬────────────────────────────────────────┘
                            ▼
            ┌────────────────────────────────────────────────────────┐
            │                 Service / Orchestration                │
            │   (coordinates, does NOT contain algorithms/SQL)      │
            └───────┬──────────────┬────────────────┬────────────────┘
                    ▼              ▼                ▼
            ┌──────────────┐  ┌──────────────────────────────┐
            │   Engines    │  │         Event Bus            │
            │  Profit,     │  │  price.changed, decision.*    │
            │  Matching,   │  │  opportunity.*, notify.*      │
            │  Sourcing,   │  │  → subscribers: analytics,    │
            │  Risk,       │  │    notifications, forecast    │
            │  Forecast,   │  └──────────────────────────────┘
            │  AI, Memory  │
            └───────┬──────┘
                    ▼
            ┌────────────────────────────────────────────────────────┐
            │                     Repositories                       │
            │   (one per aggregate; never call each other)          │
            └───────┬────────────────────────────────────────────────┘
                    ▼
            ┌────────────────────────────────────────────────────────┐
            │        ORM Models  →  PostgreSQL (Neon) / Redis        │
            │        time-series: partitioned, indexed, retention    │
            └────────────────────────────────────────────────────────┘
```

**Enforced rules (add to CI/lint):**
- `app/api` may not import `app/infrastructure` or `app/domain/models`.
- `app/domain/services` may not import `app/api` or `app/infrastructure.repositories` *of another aggregate*.
- Engines may depend on repositories/services, not on each other's internals.
- No repository imports another repository.
- No ORM model file may exceed ~200 LOC (split).

---

## 6. Engine Review

| Engine | Exists? | Where | Verdict |
|---|---|---|---|
| Profit Engine | ✅ | `app/profit/engine.py` | **Good** — pure, focused, deterministic. Keep as the gold standard. |
| Matching Engine | ✅ | `app/matching/engine.py` | **Good** — strategy pattern. Consider extracting `confidence` + `explanation` into a separate scorer. |
| Sourcing Engine | ⚠️ | `app/sourcing/engine.py` (621 LOC) | **God class** — split risk/scoring/reasoning out. |
| AI Engine | ✅ | `app/ai/reasoning.py` | OK but *coupled*: instantiated via module factory; make it injectable. |
| Analytics Engine | ⚠️ | `app/analytics/service.py` (773) | **God class** — split collector vs query. |
| **Forecast Engine** | ❌ | — | **Missing** — forecasting (BSR/sales trends) currently lives in analytics repository (`compute_trend_slope`). Extract. |
| **Risk Engine** | ❌ | — | **Missing** — risk logic buried in `SourcingEngine._determine_risk`. Extract. |
| **Decision Engine** | ❌ | — | **Missing** — BUY/WATCH/PASS policy scattered across agent + sourcing. Centralize the decision policy. |
| **Marketplace Engine** | ❌ | — | **Missing** — Amazon price/BuyBox/BSR retrieval scattered (keepa, analytics). Centralize. |
| **Supplier Engine** | ⚠️ | `app/plugins/manager.py` | **Good** abstraction; thin orchestrator. Could formalize as SupplierEngine. |
| **Notification Engine** | ⚠️ | `app/agent/notifier.py` | **Thin** — promote to first-class, subscribe to events. |
| **Knowledge Graph Engine** | ❌ | — | **Missing** — brand/category/product relations exist in ORM but no engine. |
| **Feature Engine / Feature Store** | ❌ | — | **Missing** — needed for scoring/matching at scale. |
| **Memory Engine** | ❌ | — | **Missing** — AI memory/context persistence for the assistant. |

**Principle:** each engine owns exactly one responsibility and is constructor-injected, pure where possible, and independently testable (like `ProfitEngine`).

---

## 7. Module / Dependency Analysis

### Confirmed duplication
- **Supplier-product DTOs** redefined in: `plugins/models.py`, `matching/models.py`, `agent/models.py`, `assistant/models.py`, plus ORM `domain/models/sourcing.py`. → **One canonical type + mappers.**
- **`_parse_json_response`** in `ai/reasoning.py` and `assistant/engine.py`. → shared util.
- **Logger** `app/agent/logger.py` vs `app/core/logging.py`. → single logger.
- **Money/Decimal helpers** (`_money`, `_to_decimal`) repeated. → shared money util.
- **Cross-supplier bulk loop** repeated in `PluginManager`. → one helper + `asyncio.gather`.
- **Decision/BUY-WATCH vocabulary** in agent models, sourcing, matching, analytics — several near-identical enums/fields.

### Confirmed coupling
- `SourcingEngine` → `AnalyticsRepository` (cross-module repo import) — **violates repository isolation.**
- `SourcingEngine` constructs `ProfitEngine` inline (not injected).
- `_get_ai_reasoning()` module-level factory (not injected, hard to mock).
- `main.py` hand-wires the analytics scheduler but not the agent scheduler (inconsistent lifecycle).
- `api/v1/*` are mostly thin (good), but `sourcing.py` API is 340 LOC — some logic may have leaked into the route.

### God classes (LOC)
| File | LOC | Problem |
|---|---|---|
| `analytics/service.py` | 773 | collector + query + summary + trend |
| `analytics/repository.py` | 700 | 20+ methods, many metrics |
| `sourcing/engine.py` | 621 | eval + risk + score + summary + recs |
| `domain/models/sourcing.py` | 751 | many unrelated ORM models in one file |
| `domain/seed_data.py` | 576 | large seed script |
| `integrations/keepa/client.py` | 562 | vendor client (acceptable, but isolate) |

### Module dependency graph (simplified, current — with problem edges marked)

```
api/v1 (agent, analytics, assistant, products, products_sourcing, sourcing, orders)
   │
   ├──► domain/services ──────────────► infrastructure/repositories ─► domain/models
   │         │                                  ▲
   │         └──► sourcing/engine ──────────────┘ (⚠️ imports analytics.repository directly)
   │                    │
   │                    ├──► profit/engine         (⚠️ constructed inline)
   │                    └──► ai/reasoning          (⚠️ via module factory _get_ai_reasoning)
   │
   ├──► plugins/manager ─► plugins/{base,registry,suppliers/*}
   ├──► agent/{scheduler,worker,pipeline,queue,monitor,notifier}
   ├──► analytics/{service,repository,scheduler}
   ├──► assistant/engine ─► assistant/retriever
   ├──► matching/engine ─► matching/matchers ─► (embedding → LLM provider)
   ├──► integrations/keepa/{client,service,scheduler,repository}
   └──► core/{database,redis,cache,telemetry,logging,dependencies}
        config/ (app/config, profit/config, plugins/config, keepa/config)
```

**Problem edges:** (1) engine→other-module's-repository, (2) engine→engine direct construction, (3) module factory for AI, (4) 5 modules each defining supplier-product. No circular import loops were found (good — the `from __future__ import annotations` fix removed the LLMProvider one).

---

## 8. Event Architecture — Recommendations

**Introduce an in-process async event bus** (interface compatible with Redis/RabbitMQ later). Emit on domain events, subscribe for side-effects. Recommended sync vs async:

| Event | Trigger | Consumers | Mode |
|---|---|---|---|
| `product.created` | POST /products | catalog index, analytics | async |
| `price.changed` | price update | analytics, matching, notifications | async |
| `inventory.changed` | supplier scan | forecasting, sourcing | async |
| `buybox.changed` | amazon retrieval | analytics, alerting | async |
| `opportunity.found` | sourcing eval | notifications, dashboard | async |
| `decision.created` | agent decision | decision log (append), notifications, audit | async |
| `notification.sent` | notification | audit log | async |
| `supplier.updated` | plugin data | matching, pricing | async |

**Rule:** anything that is *not* needed for the HTTP response is async via the bus. The request path stays synchronous & fast; analytics/notifications/forecast become subscribers. This removes the current inline fan-out and makes the pipeline resilient to a slow consumer.

---

## 9. Data-Flow Diagrams (key paths)

### 9.1 HTTP Request (e.g. evaluate a product)
```
Client ──POST /sourcing/evaluate──► API route
  └─ Pydantic schema (validation)
     └─ ProductSourcingService
        └─ SourcingEngine
           ├─ _gather_data → plugins/manager → suppliers (httpx)
           ├─ ProfitEngine.calculate
           ├─ AIReasoningEngine.analyze (LLM, optional)
           └─ scoring/risk
           └─ persist decision (async: emit decision.created)
     └─ response schema ──► Client
```

### 9.2 Background Job (analytics snapshot)
```
AnalyticsScheduler (every 1h)
  └─ AnalyticsService.collect_snapshot
     ├─ _collect_prices (keepa / amazon)
     ├─ _collect_sellers
     ├─ _collect_inventory
     ├─ _collect_fees
     └─ _collect_profit
  └─ AnalyticsRepository.bulk_insert_* (append-only)
```

### 9.3 Agent Workflow
```
POST /agent/start → AgentScheduler.start()
  ├─ spawn N workers (in-memory tasks)
  ├─ scheduler_loop: every cycle_interval → enqueue SCAN_SUPPLIER task
  └─ recovery_loop: restart dead workers
Worker._run_loop
  └─ TaskQueue.dequeue(timeout=5)  [⚠️ blocking BRPOP — Upstash free timeouts]
     └─ SourcingPipeline.scan_supplier / retrieve_amazon_data
        └─ _execute_task → pipeline stages → log decision
```

### 9.4 AI Workflow
```
User prompt → AssistantEngine.answer
  └─ capability detect
     ├─ retriever (vector / search)
     ├─ LLMProvider.generate (anthropic/openai/ollama, lazy)
     └─ _parse_json_response
  └─ fallback answer if LLM unavailable
```

### 9.5 Marketplace / Supplier / Forecast / Notification / Decision
```
Supplier scan → plugins → SupplierProductSearchResult
  └─ matching engine (barcode/brand/fuzzy/spec/image/embedding)
     └─ match → amazon product
Forecast: (missing engine) → currently analytics.compute_trend_slope
Decision: BUY/WATCH/PASS → decision log (append-only), notify if score>=threshold
Notification: agent/notifier → (async via bus in target state)
```

---

## 10. Performance & Scalability Assessment

| Scale | Feasibility | Key risks / actions |
|---|---|---|
| **100 products** | ✅ trivial | none |
| **10,000 products** | ✅ fine | ensure indexes on all FK + `(product_id, created_at)`; N+1 in analytics |
| **100,000 products** | ⚠️ needs work | time-series tables must be **partitioned by time**; add composite `(product_id, created_at)` indexes; batch inserts; add cache for match/scoring; parallelize cross-supplier calls |
| **1,000,000 products** | ❌ blocked | **partitioning + retention** (drop/archive > N days), **materialized aggregates** for trends, **async event-driven** analytics, **horizontal worker scaling**, embedding matching must be batched/cached (per-candidate LLM is a non-starter), read replicas |

**Concrete bottlenecks & recommendations**
1. **Sequential cross-supplier calls** (`search_all`, `lookup_all`, `compare_pricing`) → use `asyncio.gather` with per-supplier isolation. (Low effort, big win.)
2. **No caching** → add Redis cache for supplier lookups, matching results, embeddings, frequent analytics summaries. TTL-based. (Medium.)
3. **Embedding/LLM per candidate** → batch embeddings; cache by hash; move to a queue/worker. (High.)
4. **Time-series without partitioning/retention** → partition by month; index `(product_id, created_at)`; add retention policy. (High.)
5. **Analytics inline in request/scheduler** → move to event bus + dedicated workers. (High.)
6. **Agent 3 workers in one process** → separate worker processes/containers; scale horizontally with a shared Redis queue. (High.)
7. **DB connection pool** — fine now; at scale use read replicas for analytics queries. (Future.)

---

## 11. Database Review

**Current:** tables for `products`, `brands`, `categories`, `orders`, `suppliers`, `supplier_products`, `product_prices`, `amazon_prices`, `historical_inventory`, `fees`, `profit_calculations`, plus agent decision log. Good basic indexes (`products.asin` unique, `product_prices(product_id,effective_date)`, FKs).

**Gaps**
- **No partitioning** on any append-only time-series table (`*_prices`, `historical_inventory`, `fees`, `profit_calculations`). → partition by `created_at` (monthly) at scale.
- **No retention policy** — append-only data grows unbounded. → archive/drop or tier to cold storage after a window (e.g. 2 years).
- **Index coverage:** add composite `(product_id, created_at)` on every time-series table; consider partial indexes on active products.
- **Soft-delete + unique constraints:** ensure unique indexes are partial (`WHERE deleted_at IS NULL`) so re-adding a soft-deleted ASIN doesn't collide.
- **Migration drift history:** we already hit one drift bug (`products.sku` NOT NULL vs model). → add a **schema diff check** in CI (autogenerate a compare) so model↔migration never silently diverge.
- **FKs on `delete SET NULL`** are fine; verify all time-series reference `products.id` with proper cascade/retention.

---

## 12. AI Architecture Review

| Concern | Status | Verdict |
|---|---|---|
| LLM Provider abstraction | ✅ `ai/base.py` ABC + providers | **Good.** Clean, lazy-loaded, optional. Keep. |
| AI Memory | ❌ | **Missing.** Add a memory/context store for assistant + agent (ephemeral vs long-term). |
| Prompt management | ⚠️ `ai/prompts/{assistant,sourcing}.py` | Good start; move to versioned templates with parameters (no inline f-strings scattered). |
| Feature store | ❌ | **Missing.** Needed for consistent scoring/matching features. |
| Decision intelligence | ⚠️ scattered | **Consolidate** decision policy into a DecisionEngine. |
| Knowledge graph | ❌ | **Missing.** Model relations exist; add an engine + query layer. |
| Forecasting | ⚠️ in analytics | **Extract** into a ForecastEngine. |
| Provider auto-detect | ✅ `ai/providers/__init__.py` | Good (fixed lazy-annotation bug). Keep. |

**Where things belong:** LLM → `ai/`; prompts → `ai/prompts`; memory → new `ai/memory`; features → new `features` module; decisions → `decision/` engine; forecast → `forecast/` engine. Stop burying these in `analytics` and `sourcing`.

---

## 13. Security Review

| Area | Status | Risk |
|---|---|---|
| **Authentication** | ❌ none | **CRITICAL** — all endpoints + dashboard public. Add auth (JWT/OAuth) + protect `agent/start`, `products`, dashboard. |
| **Authorization** | ❌ none | CRITICAL — role-based limits (admin vs viewer) missing. |
| **API keys** | ⚠️ | Supplier keys read from config/env (good — no hardcoded keys found). Ensure they never reach clients. |
| **Secret management** | ⚠️ | Env vars on Render (fine). No key vault for rotation. Add for secrets at scale. |
| **Rate limiting** | ❌ none | CRITICAL — add per-client/IP limits (esp. public AI + sourcing endpoints). |
| **Input validation** | ✅ | Pydantic schemas everywhere (good). Keep `max_length`/patterns. |
| **Audit logging** | ⚠️ | Decision log is append-only (good). No generalized audit trail for admin/agent actions. Add. |
| **PII handling** | ⚠️ | No explicit PII policy/redaction. Define what's collected and log-redact. |
| **CORS** | ⚠️ | `allow_origins=["*"]` + `allow_credentials=True` — **invalid/insecure** combo. Fix to explicit origins. |
| **Dependency supply-chain** | ⚠️ | Pin versions (Docker hardcoded list is pinned-ish). Add `pip-audit`/SBOM in CI. |

---

## 14. Testing Review

- ✅ **249 tests pass**; strong coverage of products, profit, sourcing, plugins, agent, analytics, assistant, keepa.
- ✅ Good use of SQLite swap via repository pattern; Pydantic makes schema tests easy.
- **Weak spots**
  - `SourcingEngine` constructs `ProfitEngine` and AI inline → hard to mock in unit tests (tests likely do integration-ish setup). Inject to isolate.
  - `EmbeddingMatcher` and AI calls hit external LLMs → non-deterministic, slow tests. Add explicit mocks + cassette/vcr for external HTTP.
  - Analytics god class couples collection + query, making targeted tests heavier.
  - No tests for event bus / concurrency / Redis failure modes.
  - No contract tests for the plugin ABC (all suppliers must implement all 8 methods).
- **Recommendations:** DI injection everywhere; introduce fakes for providers; split god classes so each responsibility has a focused test; add CI schema-drift check and secret scan (gitleaks).

---

## 15. Coding Standards Review

- ✅ **Consistent folder layout** (`api/domain/infrastructure/core/...`) — good, with a few strays (`assistant`, `i18n`, `integrations/keepa`, `profit`, `sourcing`, `matching` live at `app/` root; consider a `modules/` grouping as it grows).
- ✅ **Consistent naming**, DI via `Container`/dependencies, exception mapping, async usage, `get_logger`.
- ⚠️ **Config fragmented** across `app/config/__init__.py` + `profit/config.py` + `plugins/config.py` + `keepa/config.py`. Acceptable per-module, but a single settings registry + typed per-module config would reduce drift.
- ⚠️ **Two loggers** (`core/logging` vs `agent/logger`) — unify.
- ⚠️ **Inconsistent error handling** — some modules raise domain exceptions mapped globally (good); others swallow and log (plugin manager) — that's fine for isolation but document the policy.
- ✅ Async usage consistent (all `async/await`).

---

## 16. Technical Debt — Prioritized

### Critical
| # | Item | Effort |
|---|---|---|
| C1 | Add authentication/authorization to API + dashboard | 2–3 d |
| C2 | Fix CORS `*` + credentials | 0.5 d |
| C3 | Add rate limiting (sourcing, AI, agent) | 1–2 d |
| C4 | CI schema-drift check (model ↔ migrations) — we got bitten by `products.sku` | 1 d |

### High
| # | Item | Effort |
|---|---|---|
| H1 | Inject engines via DI; remove `_get_ai_reasoning()` + inline `ProfitEngine()` | 2 d |
| H2 | Remove cross-module repo import (`SourcingEngine→AnalyticsRepository`) | 1–2 d |
| H3 | Introduce in-process event bus; move analytics/notifications to subscribers | 3–4 d |
| H4 | Split `AnalyticsService`/`AnalyticsRepository` god classes | 2–3 d |
| H5 | Split `sourcing/engine.py` (extract Risk/Scoring/Decision engines) | 2–3 d |
| H6 | Split `domain/models/sourcing.py` into per-aggregate files | 1 d |
| H7 | Agent: auto-start on boot + durable run state + non-blocking dequeue | 2 d |
| H8 | Unify canonical supplier-product DTO (kill 4 duplicates) | 1–2 d |

### Medium
| # | Item | Effort |
|---|---|---|
| M1 | Shared util for JSON-parse, money/Decimal, single logger | 1 d |
| M2 | Parallelize cross-supplier calls (`asyncio.gather`) | 1 d |
| M3 | Add Redis caching (lookups, matching, summaries, embeddings) | 2–3 d |
| M4 | Batch/cache embedding matching (stop per-candidate LLM) | 2 d |
| M5 | DB partitioning (time-series) + retention policy + composite indexes | 2–3 d |
| M6 | Prompts → versioned templates | 1 d |
| M7 | Add audit logging; define PII policy + log redaction | 1–2 d |
| M8 | Plugin ABC contract tests; gitleaks + pip-audit in CI | 1 d |

### Low
| # | Item | Effort |
|---|---|---|
| L1 | Group top-level feature dirs under `modules/` | 0.5 d |
| L2 | Seed data script cleanup (split from `domain/seed_data.py`) | 1 d |
| L3 | Docs: consolidate README/SDD with current reality | 1 d |
| L4 | Remove/disable redundant `deploy.yml` (unset secret) | 0.25 d |

---

## 17. Prioritized Improvement Roadmap

**Phase 0 — Security (do now, before anything public):** C1, C2, C3, C4.

**Phase 1 — Structural integrity (next):** H1, H2, H3, H7. Decouple engines, add event bus, make agent durable. This unblocks everything else.

**Phase 2 — Break the gods:** H4, H5, H6, H8, M1. Split analytics/sourcing/models; unify DTOs.

**Phase 3 — Performance at scale:** M2, M3, M4, M5. Parallelism, caching, batching, DB partitioning/retention.

**Phase 4 — New engines (feature-completeness):** Forecast, Risk, Decision, Marketplace, Notification, Memory, Knowledge Graph, Feature store — each following the `ProfitEngine` model, wired by events and DI.

**Phase 5 — Hardening:** M6, M7, M8, L1–L4, SBOM, secrets rotation.

---

## 18. Bottom Line

The architecture is a **good skeleton** — clean vertical layering, solid plugin & strategy abstractions, focused profit engine, disciplined repository pattern, 249 green tests. It is **not yet production-safe or production-scale** for two dominating reasons:

1. **Security** — a fully unauthenticated, publicly-exposed API. This must be fixed before *anything* else.
2. **Decoupling** — everything is synchronous, direct-call fan-out with god classes and cross-module coupling. This must be fixed before growth past ~10⁵ records.

Address Phase 0 + Phase 1 and the foundation becomes genuinely scalable. The good news: because the layers are already clean and engines like `ProfitEngine` exist, the refactors are **mechanical and low-risk** — mostly DI plumbing and extraction, not rewrites.

**Scores:** Architecture **62/100** · Production readiness **45/100** · Test coverage **good** (249 tests) but **isolation needs DI work**.
