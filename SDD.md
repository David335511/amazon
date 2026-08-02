# Software Design Document (SDD)

## Amazon AI Commerce Platform

**Version:** 1.0.0  
**Date:** 2025-07-31  
**Status:** Draft  

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Component Diagram](#2-component-diagram)
3. [Data Flow Diagram](#3-data-flow-diagram)
4. [Database ERD](#4-database-erd)
5. [API Specifications](#5-api-specifications)
6. [Plugin Architecture](#6-plugin-architecture)
7. [Background Worker Design](#7-background-worker-design)
8. [Scheduler Design](#8-scheduler-design)
9. [AI Integration Points](#9-ai-integration-points)
10. [Security Model](#10-security-model)
11. [Authentication and Authorization](#11-authentication-and-authorization)
12. [Configuration Management](#12-configuration-management)
13. [Deployment Architecture](#13-deployment-architecture)
14. [Logging and Observability](#14-logging-and-observability)
15. [Performance Targets](#15-performance-targets)
16. [Scalability Plan](#16-scalability-plan)
17. [Backup and Disaster Recovery](#17-backup-and-disaster-recovery)
18. [Testing Strategy](#18-testing-strategy)
19. [Coding Standards](#19-coding-standards)
20. [Directory Structure](#20-directory-structure)
21. [Milestone Plan](#21-milestone-plan)

---

## 1. High-Level Architecture

### 1.1 Overview

The Amazon AI Commerce Platform is a production-quality system for product sourcing, analysis, and automated decision-making. It follows a **Clean Architecture** pattern with strict layer separation, enabling testability, maintainability, and independent deployability of components.

### 1.2 Architectural Principles

| Principle | Description |
|-----------|-------------|
| **Clean Architecture** | Strict layer separation: API → Service → Domain → Infrastructure |
| **Append-Only Data** | All historical data is append-only. Never UPDATE or DELETE time-series rows |
| **RAG Pattern** | Retrieve data from database before calling LLM (Retrieval-Augmented Generation) |
| **Provider Abstraction** | All external services (LLM, suppliers) are behind abstract interfaces |
| **Error Isolation** | One component failure never cascades to others |
| **Stateless Services** | All business logic is stateless — state lives in the database |
| **Async-First** | All I/O is asynchronous using asyncio |

### 1.3 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Runtime** | Python 3.12+ | Application runtime |
| **Web Framework** | FastAPI | REST API with automatic OpenAPI docs |
| **ASGI Server** | Uvicorn | Production ASGI server |
| **Database** | PostgreSQL 16 | Primary data store |
| **Cache** | Redis 7 | Caching, queues, rate limiting |
| **ORM** | SQLAlchemy 2.x (async) | Database access |
| **Migrations** | Alembic | Schema versioning |
| **Validation** | Pydantic v2 | Request/response validation |
| **Configuration** | Pydantic Settings + YAML | Layered configuration |
| **Logging** | structlog | Structured JSON logging |
| **Observability** | OpenTelemetry | Distributed tracing, metrics |
| **Testing** | pytest, pytest-asyncio, httpx | Unit and integration tests |
| **Linting** | ruff | Code quality |
| **Type Checking** | mypy (strict) | Static type analysis |
| **Containerization** | Docker, Docker Compose | Deployment |

### 1.4 Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        API LAYER (FastAPI)                         │
│  app/api/v1/                                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │  Health  │ │ Products │ │  Orders  │ │Sourcing  │ │Assistant │ │
│  │  Agent   │ │Analytics │ │   ...    │ │          │ │          │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
├───────┼────────────┼────────────┼────────────┼────────────┼───────┤
│       │     SERVICE LAYER (Business Logic)              │         │
│  ┌────┴─────┐ ┌────┴─────┐ ┌────┴─────┐ ┌────┴─────┐           │
│  │ProductSvc│ │ OrderSvc │ │Sourcing  │ │Analytics │           │
│  │          │ │          │ │Engine    │ │Service   │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
├───────┼────────────┼────────────┼────────────┼─────────────────┤
│       │     DOMAIN LAYER (Models + Rules)              │         │
│  ┌────┴─────┐ ┌────┴─────┐ ┌────┴─────┐ ┌────┴─────┐           │
│  │  ORM     │ │ Pydantic │ │ Sourcing │ │  Profit  │           │
│  │  Models  │ │ Schemas  │ │  Rules   │ │  Engine  │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
├───────┼────────────┼────────────┼────────────┼─────────────────┤
│       │  INFRASTRUCTURE LAYER (Data Access)          │         │
│  ┌────┴─────┐ ┌────┴─────┐ ┌────┴─────┐ ┌────┴─────┐           │
│  │Repositori│ │  Keepa   │ │  Plugin  │ │  Redis   │           │
│  │   es     │ │  Client  │ │ Manager  │ │  Cache   │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────────┤
│                    DATA STORES                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  PostgreSQL   │  │    Redis     │  │  External APIs       │  │
│  │  (Primary)    │  │  (Cache+Q)  │  │  (Keepa, Suppliers)  │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.5 Module Map

| Module | Path | Responsibility |
|--------|------|----------------|
| **API** | `app/api/v1/` | Route handlers, request validation, response formatting |
| **Config** | `app/config/` | YAML + env var configuration loading |
| **Core** | `app/core/` | Database, Redis, logging, telemetry, DI container |
| **Domain** | `app/domain/` | ORM models, Pydantic schemas, business services |
| **Infrastructure** | `app/infrastructure/` | Repository implementations |
| **Integrations** | `app/integrations/` | External API clients (Keepa) |
| **Plugins** | `app/plugins/` | Supplier plugin system |
| **Profit** | `app/profit/` | Profit calculation engine |
| **Matching** | `app/matching/` | Product matching engine |
| **Analytics** | `app/analytics/` | Historical data collection and analysis |
| **Sourcing** | `app/sourcing/` | Product evaluation and scoring |
| **AI** | `app/ai/` | LLM provider abstraction, prompt management |
| **Agent** | `app/agent/` | Autonomous sourcing agent |
| **Assistant** | `app/assistant/` | AI Q&A assistant |

---

## 2. Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL ACTORS                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │  User/   │  │  Keepa   │  │ Walmart  │  │  Target  │  │  LLM Provider │  │
│  │  Client  │  │   API    │  │  Plugin  │  │  Plugin  │  │ (OpenAI/Anthropic/Ollama)│
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬───────┘  │
└───────┼──────────────┼────────────┼────────────┼──────────────────┼──────────┘
        │              │            │            │                  │
        ▼              ▼            ▼            ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          API GATEWAY (FastAPI)                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────┐ │
│  │  Health  │ │ Products │ │  Orders  │ │Sourcing  │ │Analytics │ │Agent │ │
│  │ Assistant│ │  Profit  │ │Matching  │ │  Config  │ │   AI     │ │  ... │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SERVICE LAYER                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐   │
│  │  Product     │ │  Order       │ │  Sourcing    │ │  Analytics       │   │
│  │  Service     │ │  Service     │ │  Engine      │ │  Service         │   │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────────┘   │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐   │
│  │  Profit      │ │  Matching    │ │  Assistant   │ │  AI Reasoning    │   │
│  │  Engine      │ │  Engine      │ │  Engine      │ │  Engine          │   │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      BACKGROUND WORKERS                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │  Agent Workers    │  │  Analytics       │  │  Keepa Refresh           │  │
│  │  (3-20 concurrent)│  │  Scheduler       │  │  Scheduler               │  │
│  │  Process queue    │  │  Collect hourly  │  │  Refresh product data    │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────┬───────────────┘  │
└──────────┼─────────────────────┼───────────────────────┼───────────────────┘
           │                     │                       │
           ▼                     ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DATA STORES                                         │
│  ┌────────────────────────────────────┐  ┌──────────────────────────────┐  │
│  │         PostgreSQL 16              │  │         Redis 7              │  │
│  │  ┌──────────────────────────────┐  │  │  ┌────────────────────────┐  │  │
│  │  │  Products, Orders, Brands   │  │  │  │  Cache (API responses) │  │  │
│  │  │  Categories, Suppliers      │  │  │  │  Task Queue (Agent)    │  │  │
│  │  │  Amazon Prices (append)     │  │  │  │  Rate Limiter State    │  │  │
│  │  │  Product Prices (append)    │  │  │  │  Session Store         │  │  │
│  │  │  Seller Counts (append)     │  │  │  │  Decision Log Index    │  │  │
│  │  │  Sales Estimates (append)   │  │  │  │  Worker Heartbeats     │  │  │
│  │  │  Historical Fees (append)   │  │  │  └────────────────────────┘  │  │
│  │  │  Profit Calculations (append)│  │  └──────────────────────────────┘  │
│  │  │  Historical Inventory (append)│  │                                   │
│  │  └──────────────────────────────┘  │                                   │
│  └────────────────────────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow Diagram

### 3.1 Product Sourcing Flow

```
User Request (evaluate product)
        │
        ▼
┌───────────────────┐
│  Sourcing Engine  │
│  evaluate_product │
└───────┬───────────┘
        │
        ├──→ 1. Gather Data ─────────────────────────────────────┐
        │         │                                              │
        │         ├──→ AnalyticsRepository.get_latest_amazon_price│
        │         ├──→ AnalyticsRepository.get_latest_supplier_prices│
        │         ├──→ AnalyticsRepository.get_latest_seller_count│
        │         ├──→ AnalyticsRepository.get_latest_sales_estimate│
        │         ├──→ AnalyticsRepository.get_latest_fees       │
        │         ├──→ AnalyticsRepository.get_latest_inventory  │
        │         └──→ AnalyticsRepository.compute_summary       │
        │                                                        │
        ├──→ 2. Calculate Profit ──→ ProfitEngine.calculate()    │
        │                                                        │
        ├──→ 3. Run Rules (7) ───────────────────────────────────┐│
        │    ├──→ MinimumRoiRule.evaluate()                      ││
        │    ├──→ MinimumProfitRule.evaluate()                  ││
        │    ├──→ MinimumSalesRule.evaluate()                   ││
        │    ├──→ CompetitionRule.evaluate()                   ││
        │    ├──→ BuyBoxStabilityRule.evaluate()              ││
        │    ├──→ PriceStabilityRule.evaluate()              ││
        │    └──→ InventoryAvailabilityRule.evaluate()      ││
        │                                                    ││
        ├──→ 4. Calculate Opportunity Score ──────────────────┘│
        │         weighted_score = Σ(score × weight) / Σ(weight)│
        │                                                        │
        ├──→ 5. AI Reasoning (optional) ────────────────────────┐│
        │    ├──→ Build product data dict                      ││
        │    ├──→ Retrieve prompt from registry                ││
        │    ├──→ Call LLM provider                           ││
        │    └──→ Parse JSON response → AIRecommendation     ││
        │                                                    ││
        └──→ Return ProductEvaluation ───────────────────────┘│
                                                               │
                                                               ▼
                                                    JSON Response (API)
```

### 3.2 Autonomous Agent Flow

```
AgentScheduler (every N minutes)
        │
        ▼
┌───────────────────┐
│  Create Cycle      │
│  Tasks per Supplier│
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  Task Queue (Redis)│
│  Priority 0-10     │
└───────┬───────────┘
        │
        ▼ (dequeued by worker)
┌───────────────────┐
│  Worker            │
│  (asyncio task)    │
└───────┬───────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  SourcingPipeline.run_full_pipeline()                         │
│                                                               │
│  1. Scan Supplier ──→ PluginManager.search()                  │
│  2. Retrieve Amazon ─→ AnalyticsRepository                   │
│  3. Calculate Profit → ProfitEngine                          │
│  4. Score Opportunity → SourcingEngine                        │
│  5. AI Recommendation → AIReasoningEngine (optional)          │
│  6. Log Decision ────→ DecisionLogger (append-only)           │
│  7. Notify ──────────→ Notifier (BUY/WATCH alerts)           │
└───────────────────────────────────────────────────────────────┘
```

### 3.3 AI Assistant Flow (RAG)

```
User Question
        │
        ▼
┌───────────────────┐
│  Capability        │
│  Detection         │
│  (keyword match)   │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  Data Retrieval    │
│  (AssistantRetriever)│
│  ┌─────────────┐  │
│  │ PostgreSQL   │  │
│  └─────────────┘  │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  Build Prompt     │
│  (system + context)│
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  LLM Generation   │
│  (OpenAI/Anthropic│
│   /Ollama)        │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  Parse Response   │
│  (JSON → Answer)  │
└───────┬───────────┘
        │
        ▼
    User gets answer
    + data sources
    + confidence
```

---

## 4. Database ERD

### 4.1 Entity Relationship Diagram (Textual)

```
┌──────────────┐       ┌──────────────────┐       ┌──────────────┐
│    Brand     │       │    Product        │       │   Category   │
│──────────────│       │──────────────────│       │──────────────│
│ id (PK)      │◄──────│ brand_id (FK)    │──────►│ id (PK)      │
│ name         │       │ id (PK)          │       │ name         │
│ slug         │       │ asin (UK)        │       │ slug         │
│ description  │       │ title            │       │ path         │
│ logo_url     │       │ upc, ean, gtin   │       │ level        │
│ is_active    │       │ price            │       │ parent_id(FK)│
└──────────────┘       │ description      │       └──────────────┘
                       │ is_active        │
                       │ is_amazon_fba    │
                       │ weight, dimensions│
                       └────────┬─────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
         ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   AmazonPrice     │  │   ProductPrice   │  │   SellerCount    │
│  (append-only)    │  │  (append-only)   │  │  (append-only)   │
│──────────────────│  │──────────────────│  │──────────────────│
│ id (PK)          │  │ id (PK)          │  │ id (PK)          │
│ product_id (FK)  │  │ product_id (FK)  │  │ product_id (FK)  │
│ price            │  │ supplier_id (FK) │  │ new_seller_count │
│ currency         │  │ price            │  │ used_seller_count│
│ condition        │  │ currency         │  │ fba_seller_count │
│ is_amazon_fulfill│  │ source           │  │ effective_date   │
│ is_buy_box       │  │ effective_date   │  │ (INDEX: product, │
│ effective_date   │  │ (INDEX: product, │  │  effective_date) │
│ (INDEX: product, │  │  effective_date) │  └──────────────────┘
│  effective_date)  │  └──────────────────┘
└──────────────────┘
         │                      │                      │
         ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  SalesEstimate   │  │  HistoricalFee   │  │ProfitCalculation  │
│ (append-only)    │  │  (append-only)   │  │  (append-only)   │
│──────────────────│  │──────────────────│  │──────────────────│
│ id (PK)          │  │ id (PK)          │  │ id (PK)          │
│ product_id (FK)  │  │ product_id (FK)  │  │ product_id (FK)  │
│ monthly_sales    │  │ referral_fee     │  │ unit_cost        │
│ daily_sales      │  │ fulfillment_fee  │  │ amazon_price     │
│ monthly_revenue  │  │ storage_fee      │  │ total_cost       │
│ sales_rank       │  │ total_fees       │  │ net_profit       │
│ effective_date   │  │ effective_date   │  │ roi_percentage   │
│ (INDEX: product, │  │ (INDEX: product, │  │ effective_date   │
│  effective_date)  │  │  effective_date) │  │ (INDEX: product, │
└──────────────────┘  └──────────────────┘  │  effective_date) │
                                            └──────────────────┘
         │                      │
         ▼                      ▼
┌──────────────────┐  ┌──────────────────┐
│HistoricalInventory│  │   Inventory      │
│  (append-only)    │  │  (current state) │
│──────────────────│  │──────────────────│
│ id (PK)          │  │ id (PK)          │
│ product_id (FK)  │  │ product_id (FK)  │
│ qty_on_hand      │  │ qty_on_hand      │
│ qty_reserved     │  │ qty_reserved     │
│ qty_inbound      │  │ qty_inbound      │
│ qty_available    │  │ warehouse_loc    │
│ effective_date   │  │ lot_number       │
│ (INDEX: product, │  └──────────────────┘
│  effective_date) │
└──────────────────┘

┌──────────────┐       ┌──────────────────┐       ┌──────────────┐
│   Supplier   │       │ SupplierProduct  │       │    Order     │
│──────────────│       │──────────────────│       │──────────────│
│ id (PK)      │◄──────│ supplier_id (FK) │       │ id (PK)      │
│ name         │       │ product_id (FK)  │       │ customer_id  │
│ company_name │       │ supplier_sku     │       │ status       │
│ email        │       │ supplier_price   │       │ total_amount │
│ rating       │       │ moq              │       │ shipping_addr│
│ is_active    │       │ lead_time_days   │       │ created_at   │
└──────────────┘       └──────────────────┘       └──────────────┘
```

### 4.2 Indexing Strategy

| Table | Index | Type | Purpose |
|-------|-------|------|---------|
| `amazon_prices` | `(product_id, effective_date)` | Composite B-tree | Time-series range queries |
| `product_prices` | `(product_id, effective_date)` | Composite B-tree | Time-series range queries |
| `seller_counts` | `(product_id, effective_date)` | Composite B-tree | Time-series range queries |
| `sales_estimates` | `(product_id, effective_date)` | Composite B-tree | Time-series range queries |
| `historical_fees` | `(product_id, effective_date)` | Composite B-tree | Time-series range queries |
| `profit_calculations` | `(product_id, effective_date)` | Composite B-tree | Time-series range queries |
| `historical_inventory` | `(product_id, effective_date)` | Composite B-tree | Time-series range queries |
| `products` | `asin` | Unique B-tree | ASIN lookup |
| `products` | `upc` | B-tree | UPC lookup |
| `products` | `title` | B-tree (with `ilike`) | Text search |

### 4.3 Append-Only Design

All time-series tables follow the same pattern:
- **Never UPDATE or DELETE** existing rows
- **Always INSERT** new rows with `effective_date = NOW()`
- **Composite index** on `(product_id, effective_date)` for efficient range scans
- **Keyset pagination** using `WHERE effective_date < cursor` instead of `OFFSET`

---

## 5. API Specifications

### 5.1 Base URL

All API endpoints are prefixed with `/api/v1/`.

### 5.2 Standard Response Format

**Success:**
```json
{
  "data": { ... },
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 100
  }
}
```

**Error:**
```json
{
  "error": "error_code",
  "message": "Human-readable description",
  "details": { ... }
}
```

### 5.3 Endpoint Catalog

#### Health

| Method | Path | Description | Status Codes |
|--------|------|-------------|-------------|
| GET | `/api/v1/health/live` | Liveness probe | 200 |
| GET | `/api/v1/health/ready` | Readiness probe (DB + Redis) | 200, 503 |

#### Products

| Method | Path | Description | Status Codes |
|--------|------|-------------|-------------|
| POST | `/api/v1/products/` | Create product | 201, 409 |
| GET | `/api/v1/products/` | List products (paginated) | 200 |
| GET | `/api/v1/products/{id}` | Get product by ID | 200, 404 |
| PATCH | `/api/v1/products/{id}` | Update product | 200, 404 |
| DELETE | `/api/v1/products/{id}` | Delete product | 204, 404 |

#### Orders

| Method | Path | Description | Status Codes |
|--------|------|-------------|-------------|
| POST | `/api/v1/orders/` | Create order | 201 |
| GET | `/api/v1/orders/` | List orders | 200 |
| GET | `/api/v1/orders/{id}` | Get order | 200, 404 |
| PATCH | `/api/v1/orders/{id}/status` | Update status | 200, 422 |
| POST | `/api/v1/orders/{id}/cancel` | Cancel order | 200 |

#### Product Sourcing

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/products/search/asin/{asin}` | Search by ASIN |
| GET | `/api/v1/products/search/upc/{upc}` | Search by UPC |
| GET | `/api/v1/products/search/title` | Search by title |
| GET | `/api/v1/products/{id}/pricing` | Pricing history |
| GET | `/api/v1/products/{id}/bsr` | BSR history |
| GET | `/api/v1/products/{id}/buy-box` | Buy Box history |
| GET | `/api/v1/products/{id}/sellers` | Seller counts |
| POST | `/api/v1/products/refresh` | Refresh product data |
| POST | `/api/v1/products/refresh/batch` | Batch refresh |

#### Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/analytics/products/{id}/time-series/{metric}` | Time-series data |
| GET | `/api/v1/analytics/products/{id}/summary` | Multi-metric summary |
| GET | `/api/v1/analytics/products/{id}/summary/{metric}` | Single metric summary |
| POST | `/api/v1/analytics/products/{id}/collect` | Collect snapshot |
| POST | `/api/v1/analytics/collect/batch` | Batch collect |
| GET | `/api/v1/analytics/products/{id}/coverage` | Data coverage |
| GET | `/api/v1/analytics/metrics` | List available metrics |

#### Sourcing Engine

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/sourcing/evaluate` | Evaluate products |
| GET | `/api/v1/sourcing/evaluate/{id}` | Evaluate single product |
| GET | `/api/v1/sourcing/evaluate/{id}/ai` | Evaluate with AI reasoning |
| GET | `/api/v1/sourcing/config` | Get default config |
| POST | `/api/v1/sourcing/evaluate/custom` | Evaluate with custom config |
| GET | `/api/v1/sourcing/methodology` | Scoring methodology |
| GET | `/api/v1/sourcing/ai/providers` | List AI providers |
| GET | `/api/v1/sourcing/ai/prompts` | List prompt templates |

#### Autonomous Agent

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/agent/start` | Start agent |
| POST | `/api/v1/agent/stop` | Stop agent |
| POST | `/api/v1/agent/pause` | Pause agent |
| POST | `/api/v1/agent/resume` | Resume agent |
| GET | `/api/v1/agent/status` | Agent status |
| GET | `/api/v1/agent/dashboard` | Full dashboard |
| GET | `/api/v1/agent/health` | Health check |
| GET | `/api/v1/agent/decisions` | Recent decisions |
| GET | `/api/v1/agent/decisions/{id}` | Decision by ID |
| POST | `/api/v1/agent/queue/clear` | Clear queue |
| GET | `/api/v1/agent/config` | Get config |
| PUT | `/api/v1/agent/config` | Update config |

#### AI Assistant

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/assistant/ask` | Ask a question |
| GET | `/api/v1/assistant/capabilities` | List capabilities |

### 5.4 OpenAPI Documentation

FastAPI automatically generates OpenAPI 3.1 documentation at:
- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

---

## 6. Plugin Architecture

### 6.1 Overview

The plugin system enables integration with unlimited suppliers through a standardized interface. Each supplier implements the `BaseSupplierPlugin` abstract class.

### 6.2 Plugin Interface

```python
class BaseSupplierPlugin(ABC):
    supplier_name: str      # "Walmart"
    supplier_code: str      # "walmart"
    version: str            # "1.0.0"

    async def search(query, page, page_size) → list[SupplierProductSearchResult]
    async def lookup(sku) → SupplierProductLookup | None
    async def pricing(sku) → SupplierPricing | None
    async def inventory(sku) → SupplierInventory | None
    async def shipping(sku, quantity, postal_code) → SupplierShipping | None
    async def coupon(code) → list[SupplierCoupon]
    async def availability(sku) → SupplierAvailability | None
```

### 6.3 Plugin Discovery

Plugins are auto-discovered by scanning `app/plugins/suppliers/` for classes that subclass `BaseSupplierPlugin`. No manual registration needed.

### 6.4 Plugin Lifecycle

```
PluginRegistry.discover() → finds all plugin classes
PluginManager.initialize() → creates instances with config
PluginManager.search_all() → queries all enabled suppliers
PluginManager.shutdown() → closes all plugin instances
```

### 6.5 Built-in Plugins

| Plugin | Code | Status |
|--------|------|--------|
| Walmart | `walmart` | Sample implementation |
| Target | `target` | Sample implementation |
| Home Depot | `homedepot` | Sample implementation |
| Costco | `costco` | Sample implementation |
| Best Buy | `bestbuy` | Sample implementation |

---

## 7. Background Worker Design

### 7.1 Worker Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentScheduler                            │
│  Creates SUPPLIER_CYCLE tasks at configurable intervals      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    TaskQueue (Redis)                         │
│  Priority levels 0-10 │ FIFO per level │ Retry with backoff │
│  Keys: agent:queue:p{priority} (list)                       │
│        agent:queue:task:{id} (string, JSON)                 │
│        agent:queue:running (set)                            │
│        agent:queue:counter:* (string, int)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌─────────┐ ┌─────────┐ ┌─────────┐
         │Worker 1 │ │Worker 2 │ │Worker N │
         │asyncio  │ │asyncio  │ │asyncio  │
         │task     │ │task     │ │task     │
         └────┬────┘ └────┬────┘ └────┬────┘
              │            │            │
              ▼            ▼            ▼
         ┌─────────────────────────────────────────────┐
         │           SourcingPipeline                    │
         │  scan → retrieve → calculate → score → log  │
         └─────────────────────────────────────────────┘
```

### 7.2 Worker Lifecycle

1. **Start**: Worker creates asyncio task, starts heartbeat loop
2. **Dequeue**: Blocking pop from Redis priority lists (5s timeout)
3. **Process**: Execute task with configurable timeout (default: 120s)
4. **Complete**: Mark task as SUCCESS, update counters
5. **Fail**: Mark as FAILED, optionally retry with exponential backoff
6. **Heartbeat**: Update Redis every 30s with worker status
7. **Stop**: Cancel task, mark as stopped

### 7.3 Task Types

| Task Type | Payload | Description |
|-----------|---------|-------------|
| `SCAN_SUPPLIER` | `{supplier_code, page}` | Scan a supplier page |
| `RETRIEVE_AMAZON` | `{asin}` | Get Amazon product data |
| `FULL_PIPELINE` | `{supplier_code, sku, title, price}` | Full evaluation |
| `SUPPLIER_CYCLE` | `{supplier_code}` | Complete supplier cycle |

### 7.4 Retry Policy

- Max retries: 3 (configurable)
- Backoff: `retry_count × 10` seconds (10s, 20s, 30s)
- After max retries: task marked as FAILED permanently
- Scheduled retries stored in Redis with TTL

### 7.5 Auto-Recovery

The recovery loop runs every 30 seconds:
1. Check all worker heartbeats
2. If a worker has stopped unexpectedly, create a replacement
3. Update agent status (RUNNING, DEGRADED, ERROR)

---

## 8. Scheduler Design

### 8.1 Analytics Scheduler

```python
class AnalyticsScheduler:
    full_collection_interval: 3600s (1 hour)
    watchlist_interval: 900s (15 minutes)
    batch_size: 50 products

    async def _run_full_collection():
        # Every hour: collect snapshots for all active products
        # Processes in batches of 50
        # Logs progress after each batch

    async def _run_watchlist_collection():
        # Every 15 minutes: collect for watchlist products
        # Only if watchlist_provider is configured
```

### 8.2 Agent Scheduler

```python
class AgentScheduler:
    cycle_interval_minutes: 60 (1 hour)
    worker_count: 3 (configurable)

    async def _scheduler_loop():
        # Wait 10s for initial cycle
        # Every N minutes: create SUPPLIER_CYCLE tasks
        # Skip if paused
        # Auto-recover on failure

    async def _run_cycle():
        # Get enabled suppliers from PluginManager
        # Create one SUPPLIER_CYCLE task per supplier
        # Enqueue all tasks
        # Wait for completion (poll queue, max 10min)
        # Update run info
```

### 8.3 Keepa Refresh Scheduler

```python
class KeepaRefreshJob:
    watchlist_interval: 3600s (1 hour)
    batch_interval: 86400s (24 hours)

    async def _run_watchlist_refresh():
        # Refresh all products in user watchlists

    async def _run_batch_refresh():
        # Refresh a fixed batch of ASINs
```

---

## 9. AI Integration Points

### 9.1 Provider Abstraction

```python
class LLMProvider(ABC):
    provider_name: str

    async def generate(system_prompt, user_prompt) → LLMResponse
    async def generate_with_retry(system_prompt, user_prompt) → LLMResponse
    async def is_available() → bool
```

### 9.2 Supported Providers

| Provider | Env Variable | Default Model | SDK |
|----------|-------------|---------------|-----|
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o` | `openai` |
| **Anthropic** | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-20241022` | `anthropic` |
| **Ollama** | `OLLAMA_BASE_URL` | `llama3.2` | None (HTTP) |

### 9.3 Auto-Detection

```python
def create_provider(provider_type=None):
    if not provider_type:
        if os.environ.get("ANTHROPIC_API_KEY"):  → Anthropic
        elif os.environ.get("OPENAI_API_KEY"):   → OpenAI
        elif os.environ.get("OLLAMA_BASE_URL"):  → Ollama
        else: return None  # No provider available
```

### 9.4 Integration Points

| Component | AI Usage | Provider |
|-----------|----------|----------|
| **Sourcing Engine** | `AIReasoningEngine.analyze()` → Buy/Watch/Avoid recommendation | Any |
| **AI Assistant** | `AssistantEngine.answer()` → Natural language Q&A | Any |
| **Prompt Registry** | Version-controlled templates in `app/ai/prompts/` | N/A |

### 9.5 Prompt Management

- Prompts stored in `app/ai/prompts/` — separate from business logic
- Each prompt has a name and version (e.g., `assistant_v1` → `1.0.0`)
- Registry provides `get_prompt(name, data)` → `(system_prompt, user_prompt)`
- New prompts can be added without modifying existing code

### 9.6 Fallback Behavior

When no LLM provider is available:
- **Sourcing Engine**: Falls back to rule-based reasoning using opportunity score
- **AI Assistant**: Falls back to listing retrieved data without LLM analysis

---

## 10. Security Model

### 10.1 Principles

| Principle | Implementation |
|-----------|---------------|
| **Defense in Depth** | Multiple security layers: network, application, data |
| **Least Privilege** | Database users have minimal required permissions |
| **Secure by Default** | All endpoints require authentication unless explicitly public |
| **Input Validation** | All input validated by Pydantic schemas |
| **No Secrets in Code** | All secrets via environment variables |

### 10.2 API Security

- **CORS**: Configurable allowed origins via settings
- **Rate Limiting**: Optional, configurable via feature flags
- **Request Validation**: Pydantic validates all input at the API layer
- **SQL Injection**: Prevented by SQLAlchemy parameterized queries

### 10.3 Data Security

- **Append-Only Tables**: Historical data cannot be modified or deleted
- **Soft Delete**: All user-modifiable data uses soft delete
- **Audit Trail**: All decisions logged immutably

### 10.4 Secret Management

| Secret | Source | Example |
|--------|--------|---------|
| Database URL | `DATABASE_URL` env var | `postgresql+asyncpg://user:pass@host:5432/db` |
| Redis URL | `REDIS_URL` env var | `redis://user:pass@host:6379/0` |
| API Keys | `*_API_KEY` env vars | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| App Secret | `APP_SECRET_KEY` env var | Random string |

---

## 11. Authentication and Authorization

### 11.1 Current State

The platform has a **User** model with roles (`user`, `admin`, `manager`) but authentication middleware is not yet implemented. The system is designed for future integration with:

- JWT-based authentication
- OAuth2 with social providers
- API key authentication for programmatic access

### 11.2 User Model

```python
class User(Base):
    email: str          # Unique, used for login
    username: str       # Unique, display name
    password_hash: str  # bcrypt hashed
    role: str           # user, admin, manager
    is_active: bool
    email_verified_at: datetime | None
    last_login_at: datetime | None
```

### 11.3 Role-Based Access Control (Planned)

| Role | Permissions |
|------|------------|
| **admin** | Full access: manage users, products, suppliers, agent config |
| **manager** | Create/update products, view analytics, run agent |
| **user** | View products, run evaluations, use assistant |

### 11.4 API Key Authentication (Planned)

- API keys stored as hashed values
- Rate limiting per key
- Key rotation support
- Scoped permissions per key

---

## 12. Configuration Management

### 12.1 Layered Configuration

```
┌─────────────────────────────────────────────┐
│ 1. YAML Files (config/*.yaml)                │
│    Environment-specific defaults             │
│    ├── config/development.yaml               │
│    ├── config/production.yaml               │
│    └── config/testing.yaml                  │
├─────────────────────────────────────────────┤
│ 2. Environment Variables                    │
│    Override specific values                 │
│    DATABASE_URL, REDIS_URL, APP_SECRET_KEY  │
├─────────────────────────────────────────────┤
│ 3. Pydantic Settings                        │
│    Validates all config at startup          │
│    Type coercion, default values            │
└─────────────────────────────────────────────┘
```

### 12.2 Configuration Sections

```yaml
# config/development.yaml
app:
  name: "Amazon"
  debug: true
  log_level: "DEBUG"

database:
  url: "postgresql+asyncpg://amazon:amazon@localhost:5432/amazon"
  pool_size: 10
  echo: false

redis:
  url: "redis://localhost:6379/0"

server:
  host: "0.0.0.0"
  port: 8000
  reload: true

telemetry:
  enabled: true
  service_name: "amazon"
  exporter_otlp_endpoint: "http://localhost:4317"

features:
  enable_swagger: true
  enable_metrics: true
```

### 12.3 Settings Class

```python
class Settings(BaseSettings):
    app: AppConfig
    database: DatabaseConfig
    redis: RedisConfig
    server: ServerConfig
    logging: LoggingConfig
    telemetry: TelemetryConfig
    features: FeaturesConfig

    @classmethod
    def load(env: str | None = None) → Settings
    # Singleton — caches loaded instance
```

---

## 13. Deployment Architecture

### 13.1 Docker Compose (Development)

```
┌─────────────────────────────────────────────────────────────┐
│                        Docker Host                            │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  app:8000     │  │  db:5432     │  │  redis:6379      │   │
│  │  FastAPI      │  │  PostgreSQL  │  │  Redis 7         │   │
│  │  Uvicorn      │  │  16 Alpine   │  │  Alpine          │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                 │                    │             │
│         └─────────────────┼────────────────────┘             │
│                           │                                  │
│                    ┌──────┴───────┐                          │
│                    │  otel-collector│                         │
│                    │  :4317, :8888 │                          │
│                    └──────────────┘                          │
│                                                               │
│  Volumes: postgres-data, redis-data                           │
│  Network: amazon-network (bridge)                             │
└─────────────────────────────────────────────────────────────┘
```

### 13.2 Production Architecture (Recommended)

```
                         ┌─────────────┐
                         │   Load      │
                         │  Balancer   │
                         │  (nginx/ALB)│
                         └──────┬──────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
        ┌──────────┐     ┌──────────┐     ┌──────────┐
        │  App     │     │  App     │     │  App     │
        │Instance 1│     │Instance 2│     │Instance N│
        │:8000     │     │:8000     │     │:8000     │
        └────┬─────┘     └────┬─────┘     └────┬─────┘
             │                │                 │
             └────────────────┼─────────────────┘
                              │
                    ┌─────────┴──────────┐
                    │                    │
                    ▼                    ▼
              ┌──────────┐        ┌──────────┐
              │PostgreSQL│        │  Redis   │
              │ Primary  │        │ Primary  │
              │    +     │        │   +      │
              │ Replica  │        │ Replica  │
              └──────────┘        └──────────┘
```

### 13.3 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | Environment name |
| `APP_DEBUG` | `true` | Enable debug mode |
| `APP_LOG_LEVEL` | `DEBUG` | Logging level |
| `APP_SECRET_KEY` | — | Application secret |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Database connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `SERVER_HOST` | `0.0.0.0` | Bind address |
| `SERVER_PORT` | `8000` | Port |
| `OTEL_SERVICE_NAME` | `amazon` | OpenTelemetry service name |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP endpoint |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OLLAMA_BASE_URL` | — | Ollama base URL |

---

## 14. Logging and Observability

### 14.1 Structured Logging (structlog)

```python
# Log format (JSON):
{
  "event": "Product evaluated",
  "level": "info",
  "timestamp": "2025-07-31T12:00:00Z",
  "logger": "app.sourcing.engine",
  "product_id": "c0001...",
  "asin": "B0TEST",
  "score": 75.0,
  "request_id": "req-123"
}
```

### 14.2 Log Levels

| Level | Usage |
|-------|-------|
| `DEBUG` | Detailed debugging, data point counts |
| `INFO` | Business events: product evaluated, cycle complete, worker started |
| `WARNING` | Recoverable issues: API failure, retry scheduled, cache miss |
| `ERROR` | Unrecoverable: task failed permanently, worker crash, DB connection lost |
| `CRITICAL` | System-level: application startup failure, data corruption |

### 14.3 OpenTelemetry

| Instrumentation | Traces | Metrics |
|----------------|--------|---------|
| FastAPI requests | ✓ Request duration, status code | ✓ Request count, latency |
| SQLAlchemy queries | ✓ Query duration, rows affected | ✓ Query count, pool status |
| Redis commands | ✓ Command duration | ✓ Connection count |
| Custom business metrics | — | ✓ Products evaluated, decisions made |

### 14.4 Key Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `products.evaluated` | Counter | Total products evaluated |
| `products.evaluation_duration` | Histogram | Evaluation time in ms |
| `agent.tasks.completed` | Counter | Tasks completed by workers |
| `agent.tasks.failed` | Counter | Tasks failed |
| `agent.cycle.duration` | Histogram | Cycle duration in seconds |
| `agent.queue.depth` | Gauge | Current queue depth |
| `assistant.queries` | Counter | Assistant queries answered |
| `assistant.latency` | Histogram | Assistant response time |
| `db.connection_pool.size` | Gauge | Active DB connections |
| `redis.connected_clients` | Gauge | Connected Redis clients |

### 14.5 Monitoring Dashboard (Agent)

The `AgentMonitor` provides real-time observability:

```json
{
  "agent": { "status": "running", "cycle_count": 42, "uptime_seconds": 3600 },
  "workers": [{ "id": "worker-1", "status": "busy", "tasks_completed": 150 }],
  "queue": { "depth": 5, "total_completed": 1200, "total_failed": 3 },
  "decisions": { "total": 850, "recent_buy": 12, "recent_watch": 25 },
  "errors": ["Supplier scan failed for walmart: timeout"]
}
```

---

## 15. Performance Targets

### 15.1 API Response Times

| Endpoint | Target p50 | Target p95 | Target p99 |
|----------|-----------|-----------|-----------|
| Health check | 5ms | 10ms | 20ms |
| Product CRUD | 20ms | 50ms | 100ms |
| Product search | 50ms | 150ms | 300ms |
| Time-series query (1000 pts) | 100ms | 300ms | 500ms |
| Sourcing evaluation | 200ms | 500ms | 1000ms |
| AI assistant (with LLM) | 2000ms | 5000ms | 10000ms |
| AI assistant (fallback) | 200ms | 500ms | 1000ms |

### 15.2 Throughput

| Operation | Target |
|-----------|--------|
| API requests per second | 500 |
| Concurrent WebSocket connections | 1000 |
| Agent tasks per minute | 60 |
| Analytics data points ingested per second | 1000 |

### 15.3 Data Volume

| Table | Estimated Rows | Growth Rate |
|-------|---------------|-------------|
| `amazon_prices` | 10M+ | ~100K/day |
| `product_prices` | 1M+ | ~10K/day |
| `seller_counts` | 1M+ | ~10K/day |
| `sales_estimates` | 1M+ | ~10K/day |
| `historical_fees` | 1M+ | ~10K/day |
| `profit_calculations` | 1M+ | ~10K/day |
| `historical_inventory` | 500K+ | ~5K/day |

### 15.4 Query Performance

| Query Pattern | Target | Index Used |
|--------------|--------|------------|
| Latest price for product | <5ms | `(product_id, effective_date DESC)` |
| Price history (90 days) | <50ms | `(product_id, effective_date)` |
| Summary statistics | <100ms | `(product_id, effective_date)` |
| Product search by title | <200ms | `title` with `ilike` |
| Batch insert (100 rows) | <500ms | N/A |

---

## 16. Scalability Plan

### 16.1 Horizontal Scaling

| Component | Strategy | Notes |
|-----------|----------|-------|
| **API Servers** | Add instances behind load balancer | Stateless — no session affinity needed |
| **Workers** | Increase `worker_count` in AgentConfig | More concurrent task processing |
| **PostgreSQL** | Read replicas for analytics queries | Writes go to primary |
| **Redis** | Cluster mode for larger queues | Data sharded across nodes |

### 16.2 Vertical Scaling

| Component | Upgrade Path |
|-----------|-------------|
| **PostgreSQL** | Increase `work_mem`, `shared_buffers`, `effective_cache_size` |
| **Redis** | Increase `maxmemory`, enable `jemalloc` |
| **Application** | Increase `pool_size` and `max_overflow` for DB connections |

### 16.3 Database Optimization

- **Composite indexes** on `(product_id, effective_date)` for all time-series tables
- **Keyset pagination** instead of `OFFSET` for large result sets
- **Batch inserts** for high-volume data ingestion
- **Materialized views** for complex aggregations (future)
- **Table partitioning** by `effective_date` for time-series tables (future)

### 16.4 Caching Strategy

| Cache | TTL | Invalidation |
|-------|-----|-------------|
| API responses (Redis) | 5 min | On data refresh |
| Product detail (Redis) | 15 min | On product update |
| Summary statistics (Redis) | 30 min | On new data point |
| Keepa API responses (Redis) | 1 hour | On refresh |

---

## 17. Backup and Disaster Recovery

### 17.1 Backup Strategy

| Data | Method | Frequency | Retention |
|------|--------|-----------|-----------|
| PostgreSQL | `pg_dump` | Daily | 30 days |
| PostgreSQL WAL | Continuous archiving | Continuous | 7 days |
| Redis | `SAVE` / `BGSAVE` | Hourly | 7 days |
| Configuration | Git | Every change | Permanent |

### 17.2 Recovery Point Objectives (RPO)

| Data | RPO |
|------|-----|
| Product data | 1 hour |
| Historical analytics | 24 hours |
| Agent decisions | 1 hour |
| Configuration | Immediate (Git) |

### 17.3 Recovery Time Objectives (RTO)

| Scenario | RTO |
|----------|-----|
| Application crash | 5 minutes |
| Database failure | 1 hour |
| Full region failure | 4 hours |

### 17.4 Disaster Recovery Procedures

1. **Application failure**: Docker Compose restart, health check auto-recovery
2. **Database failure**: Restore from latest `pg_dump` + WAL replay
3. **Redis failure**: Restore from `dump.rdb`, queue tasks are re-creatable
4. **Full system failure**: 
   - Provision new infrastructure
   - Restore PostgreSQL from backup
   - Restore Redis from backup
   - Deploy application from Git
   - Run database migrations
   - Verify health checks

---

## 18. Testing Strategy

### 18.1 Test Pyramid

```
         ╱╲
        ╱  ╲          E2E Tests (5%)
       ╱    ╲
      ╱──────╲
     ╱        ╲       Integration Tests (25%)
    ╱          ╲
   ╱────────────╲
  ╱              ╲    Unit Tests (70%)
 ╱                ╲
╱──────────────────╲
```

### 18.2 Test Categories

| Category | Count | Tools | What's Tested |
|----------|-------|-------|---------------|
| **Unit Tests** | 170+ | pytest | Rules, models, scoring, profit engine, AI providers |
| **Integration Tests** | 60+ | pytest + aiosqlite | Repository, service, pipeline, retriever |
| **API Tests** | 30+ | pytest + httpx | Endpoints, validation, error handling |
| **Property Tests** | (future) | hypothesis | Invariant testing for scoring |

### 18.3 Test Configuration

```python
# conftest.py
# - In-memory SQLite database (aiosqlite)
# - Mock Redis client
# - Fresh database per test function
# - Overridden FastAPI dependencies
```

### 18.4 Test Coverage Targets

| Module | Target | Current |
|--------|--------|---------|
| `app/sourcing/` | 95% | ~92% |
| `app/profit/` | 95% | ~90% |
| `app/analytics/` | 90% | ~88% |
| `app/ai/` | 90% | ~95% |
| `app/agent/` | 85% | ~85% |
| `app/assistant/` | 90% | ~90% |
| `app/domain/` | 80% | ~75% |
| `app/api/` | 90% | ~85% |

### 18.5 Testing Tools

| Tool | Purpose |
|------|---------|
| pytest | Test runner |
| pytest-asyncio | Async test support |
| pytest-cov | Coverage reporting |
| httpx | HTTP client for API tests |
| aiosqlite | In-memory SQLite for test DB |
| unittest.mock | Mocking external services |
| ruff | Linting |
| mypy | Static type checking |

---

## 19. Coding Standards

### 19.1 Python Style

- **Line length**: 100 characters
- **Quotes**: Double quotes for strings
- **Indentation**: 4 spaces (no tabs)
- **Line endings**: LF (Unix)
- **Imports**: isort-sorted (stdlib → third-party → local)

### 19.2 Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Classes | PascalCase | `ProductService`, `SourcingEngine` |
| Functions/Methods | snake_case | `evaluate_product()`, `get_latest_price()` |
| Variables | snake_case | `product_id`, `opportunity_score` |
| Constants | UPPER_CASE | `DEFAULT_MATCHERS`, `MAX_RETRIES` |
| Private members | `_` prefix | `_calculate_confidence()`, `_repo` |
| Type variables | PascalCase | `ModelT`, `T` |

### 19.3 Documentation

- All modules have docstrings explaining design decisions
- All public methods have Google-style docstrings
- Complex algorithms include inline comments
- README.md documents architecture and setup

### 19.4 Type Annotations

- All functions must have type annotations
- Use `from __future__ import annotations` for forward references
- Use `TYPE_CHECKING` for circular imports
- mypy runs in strict mode

### 19.5 Error Handling

- Domain-specific exceptions (e.g., `ProductNotFoundError`)
- Global exception handlers translate to HTTP responses
- Never catch bare `except:` — always specify exception type
- Log exceptions with `logger.exception()` for traceback

### 19.6 Async Patterns

- All I/O is async (database, Redis, HTTP, LLM)
- Use `asyncio.gather()` for concurrent operations
- Use `asyncio.timeout()` for task timeouts
- Avoid `asyncio.create_task()` in request handlers

---

## 20. Directory Structure

```
amazon/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI application factory
│   │
│   ├── api/v1/                          # API routes
│   │   ├── __init__.py                  # Router aggregation
│   │   ├── agent.py                     # Agent management endpoints
│   │   ├── analytics.py                 # Historical analytics endpoints
│   │   ├── assistant.py                 # AI assistant endpoints
│   │   ├── health.py                    # Health check endpoints
│   │   ├── orders.py                    # Order CRUD endpoints
│   │   ├── products.py                  # Product CRUD endpoints
│   │   ├── products_sourcing.py         # Product sourcing endpoints
│   │   └── sourcing.py                  # Sourcing engine endpoints
│   │
│   ├── config/                          # Configuration management
│   │   └── __init__.py                  # Settings class + YAML loader
│   │
│   ├── core/                            # Core infrastructure
│   │   ├── __init__.py
│   │   ├── cache.py                    # Redis-backed response cache
│   │   ├── database.py                 # Async SQLAlchemy engine + session
│   │   ├── dependencies.py             # DI container
│   │   ├── logging.py                  # structlog configuration
│   │   ├── redis.py                    # Redis connection management
│   │   └── telemetry.py                # OpenTelemetry configuration
│   │
│   ├── domain/                          # Domain layer
│   │   ├── __init__.py
│   │   ├── seed_data.py                # Sample data for development
│   │   ├── models/                     # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── base.py                 # Declarative base + mixins
│   │   │   ├── brand.py
│   │   │   ├── category.py
│   │   │   ├── historical_inventory.py # Append-only inventory snapshots
│   │   │   ├── order.py
│   │   │   ├── product.py
│   │   │   └── sourcing.py             # All sourcing-related models
│   │   ├── schemas/                    # Pydantic request/response DTOs
│   │   │   ├── __init__.py
│   │   │   ├── order.py
│   │   │   ├── product.py
│   │   │   └── product_sourcing.py
│   │   └── services/                   # Business logic services
│   │       ├── __init__.py
│   │       ├── order_service.py
│   │       ├── product_service.py
│   │       └── product_sourcing_service.py
│   │
│   ├── infrastructure/                  # Data access layer
│   │   ├── __init__.py
│   │   └── repositories/               # Repository implementations
│   │       ├── __init__.py
│   │       ├── base.py                 # Generic CRUD repository
│   │       ├── order_repository.py
│   │       ├── product_repository.py
│   │       └── product_sourcing_repository.py
│   │
│   ├── integrations/                   # External API clients
│   │   └── keepa/
│   │       ├── __init__.py
│   │       ├── client.py               # Keepa HTTP client
│   │       ├── config.py               # Keepa configuration
│   │       ├── models.py               # Keepa data models
│   │       ├── repository.py           # Keepa data storage
│   │       ├── scheduler.py            # Background refresh jobs
│   │       └── service.py              # Keepa orchestration
│   │
│   ├── plugins/                         # Supplier plugin system
│   │   ├── __init__.py
│   │   ├── base.py                     # BaseSupplierPlugin ABC
│   │   ├── config.py                   # Plugin configuration
│   │   ├── errors.py                   # Plugin-specific errors
│   │   ├── manager.py                  # Plugin lifecycle manager
│   │   ├── models.py                   # Standardized I/O models
│   │   ├── registry.py                 # Plugin discovery registry
│   │   └── suppliers/                  # Supplier implementations
│   │       ├── __init__.py
│   │       ├── bestbuy.py
│   │       ├── costco.py
│   │       ├── homedepot.py
│   │       ├── target.py
│   │       └── walmart.py
│   │
│   ├── profit/                          # Profit calculation engine
│   │   ├── __init__.py
│   │   ├── config.py                   # Fee schedules
│   │   ├── engine.py                   # Profit calculation logic
│   │   └── models.py                   # Input/output models
│   │
│   ├── matching/                        # Product matching engine
│   │   ├── __init__.py
│   │   ├── benchmark.py                # Match scenario benchmarks
│   │   ├── engine.py                   # Matching orchestration
│   │   ├── matchers.py                 # Individual matcher implementations
│   │   └── models.py                   # Match request/response models
│   │
│   ├── analytics/                       # Historical analytics
│   │   ├── __init__.py
│   │   ├── repository.py              # Time-series queries
│   │   ├── schemas.py                 # Analytics DTOs
│   │   ├── scheduler.py              # Background collection
│   │   └── service.py                # Collection + summary stats
│   │
│   ├── sourcing/                        # Sourcing engine
│   │   ├── __init__.py
│   │   ├── engine.py                  # Evaluation orchestration
│   │   ├── models.py                  # Rules, scores, evaluations
│   │   ├── rules.py                   # 7 sourcing rules
│   │   └── scoring.py                 # Methodology documentation
│   │
│   ├── ai/                              # AI integration
│   │   ├── __init__.py
│   │   ├── base.py                    # LLMProvider ABC
│   │   ├── reasoning.py               # AI reasoning engine
│   │   ├── providers/                 # LLM provider implementations
│   │   │   ├── __init__.py            # Provider factory
│   │   │   ├── anthropic.py
│   │   │   ├── ollama.py
│   │   │   └── openai.py
│   │   └── prompts/                    # Version-controlled prompts
│   │       ├── __init__.py            # Prompt registry
│   │       ├── assistant.py           # Assistant prompts
│   │       └── sourcing.py            # Sourcing analysis prompts
│   │
│   ├── agent/                           # Autonomous sourcing agent
│   │   ├── __init__.py
│   │   ├── logger.py                  # Append-only decision log
│   │   ├── models.py                  # Task, worker, agent models
│   │   ├── monitor.py                 # Real-time monitoring
│   │   ├── notifier.py               # Notification system
│   │   ├── pipeline.py               # Full sourcing pipeline
│   │   ├── queue.py                   # Redis-backed task queue
│   │   ├── scheduler.py              # Agent lifecycle manager
│   │   └── worker.py                 # Concurrent task workers
│   │
│   └── assistant/                      # AI Q&A assistant
│       ├── __init__.py
│       ├── engine.py                  # RAG orchestration
│       ├── models.py                  # Request/response models
│       └── retriever.py              # Database retrieval layer
│
├── alembic/                            # Database migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_create_initial_tables.py
│       ├── 0002_create_sourcing_tables.py
│       └── 0003_create_historical_inventory.py
│
├── config/                             # YAML environment configs
│   ├── development.yaml
│   ├── production.yaml
│   └── testing.yaml
│
├── docker/                             # Docker configuration
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── otel-collector.yaml
│
├── tests/                              # Test suite
│   ├── __init__.py
│   ├── conftest.py                    # Shared fixtures
│   ├── test_agent.py                  # 28 tests
│   ├── test_ai.py                     # 17 tests
│   ├── test_analytics.py              # 29 tests
│   ├── test_assistant.py              # 29 tests
│   ├── test_health.py                 # 3 tests
│   ├── test_keepa_client.py          # 12 tests
│   ├── test_keepa_service.py         # 10 tests
│   ├── test_orders.py                # 12 tests
│   ├── test_plugins.py               # 20 tests
│   ├── test_products.py              # 11 tests
│   ├── test_product_sourcing_api.py  # 10 tests
│   ├── test_product_sourcing_service.py # 12 tests
│   ├── test_profit.py                # 20 tests
│   └── test_sourcing.py              # 32 tests
│
├── .env.example                        # Environment template
├── .gitignore
├── alembic.ini                         # Alembic configuration
├── docker-compose.yml                  # Full stack orchestration
├── pyproject.toml                      # Project metadata + tooling
└── README.md                           # Project documentation
```

---

## 21. Milestone Plan

### Phase 1: Foundation (Completed)

| Milestone | Deliverables | Status |
|-----------|-------------|--------|
| M1.1 Core Infrastructure | FastAPI app factory, DB, Redis, logging, telemetry | ✅ |
| M1.2 Domain Models | Product, Order, Brand, Category ORM models | ✅ |
| M1.3 API Routes | Health, Products CRUD, Orders CRUD | ✅ |
| M1.4 Database Migrations | Initial tables + sourcing tables | ✅ |
| M1.5 Testing Framework | pytest, conftest, in-memory SQLite | ✅ |

### Phase 2: Sourcing Intelligence (Completed)

| Milestone | Deliverables | Status |
|-----------|-------------|--------|
| M2.1 Profit Engine | Fee calculation, ROI, margin, break-even | ✅ |
| M2.2 Product Matching | 6 matchers, weighted scoring, explanations | ✅ |
| M2.3 Keepa Integration | Client, rate limiting, caching, repository | ✅ |
| M2.4 Plugin System | ABC, registry, manager, 5 sample plugins | ✅ |
| M2.5 Product Sourcing | Search, pricing history, BSR, Buy Box | ✅ |

### Phase 3: Analytics & Scoring (Completed)

| Milestone | Deliverables | Status |
|-----------|-------------|--------|
| M3.1 Historical Analytics | Append-only snapshots, time-series queries | ✅ |
| M3.2 Summary Statistics | Min, max, mean, median, percentiles, trends | ✅ |
| M3.3 Sourcing Engine | 7 rules, weighted scoring, opportunity score | ✅ |
| M3.4 Scoring Methodology | Documented v1.0.0 methodology | ✅ |
| M3.5 Analytics Scheduler | Background collection, batch processing | ✅ |

### Phase 4: AI Integration (Completed)

| Milestone | Deliverables | Status |
|-----------|-------------|--------|
| M4.1 LLM Provider Abstraction | ABC, OpenAI, Anthropic, Ollama providers | ✅ |
| M4.2 Prompt Management | Version-controlled prompts, registry | ✅ |
| M4.3 AI Reasoning Engine | Buy/Watch/Avoid, pros/cons/risks, fallback | ✅ |
| M4.4 AI Assistant | RAG pattern, 9 capabilities, auto-detection | ✅ |
| M4.5 Assistant Retriever | Database retrieval layer for each capability | ✅ |

### Phase 5: Automation (Completed)

| Milestone | Deliverables | Status |
|-----------|-------------|--------|
| M5.1 Task Queue | Redis-backed, priority levels, retry | ✅ |
| M5.2 Concurrent Workers | asyncio pool, heartbeat, timeout, recovery | ✅ |
| M5.3 Sourcing Pipeline | Scan → retrieve → calculate → score → log → notify | ✅ |
| M5.4 Agent Scheduler | Cycle management, pause/resume, monitoring | ✅ |
| M5.5 Decision Logger | Append-only audit trail, stats | ✅ |

### Phase 6: Production Readiness (In Progress)

| Milestone | Deliverables | Status | ETA |
|-----------|-------------|--------|-----|
| M6.1 Authentication | JWT auth, OAuth2, API keys | 🔜 | Week 1 |
| M6.2 Rate Limiting | Per-user, per-endpoint rate limits | 🔜 | Week 1 |
| M6.3 Production Docker | Multi-stage build, health checks | 🔜 | Week 2 |
| M6.4 CI/CD Pipeline | GitHub Actions, automated tests, deploy | 🔜 | Week 2 |
| M6.5 Database Optimization | Partitioning, materialized views, connection pooling | 🔜 | Week 3 |

### Phase 7: Advanced Features (Planned)

| Milestone | Deliverables | ETA |
|-----------|-------------|-----|
| M7.1 Real Supplier Plugins | Walmart, Target, Home Depot API integrations | Month 2 |
| M7.2 Web Dashboard | React/Next.js frontend | Month 2 |
| M7.3 Email/SMS Notifications | SendGrid, Twilio integration | Month 2 |
| M7.4 A/B Testing | Prompt version comparison, scoring config experiments | Month 3 |
| M7.5 Multi-Tenant | Organization isolation, team management | Month 3 |

### Current Test Status

```
243 passed, 6 failed (pre-existing profit engine precision bugs)
Coverage: ~85% across all modules
```

---

*Document version 1.0.0 — Generated 2025-07-31*
