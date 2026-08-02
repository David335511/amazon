# Amazon AI Commerce Platform

A production-quality AI commerce platform built with Python 3.12, FastAPI, PostgreSQL, Redis, and OpenTelemetry.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     API Layer (FastAPI)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  Health  │  │ Products │  │  Orders  │  │   ...   │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
├───────┼──────────────┼─────────────┼──────────────┼──────┤
│       │     Service Layer (Business Logic)         │      │
│  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐         │      │
│  │ProductSvc│  │ OrderSvc │  │   ...   │         │      │
│  └────┬─────┘  └────┬─────┘  └────┬────┘         │      │
├───────┼──────────────┼─────────────┼──────────────┼──────┤
│       │  Infrastructure (Repositories)             │      │
│  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐         │      │
│  │ProductRepo│  │OrderRepo │  │   ...   │         │      │
│  └────┬─────┘  └────┬─────┘  └────┬────┘         │      │
├───────┼──────────────┼─────────────┼──────────────┼──────┤
│       │     Data Stores              │  Observability    │
│  ┌────┴─────┐  ┌────┴─────┐  ┌──────┴──────┐           │
│  │PostgreSQL │  │  Redis   │  │OpenTelemetry│           │
│  └──────────┘  └──────────┘  └─────────────┘           │
└─────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Layered Architecture (Clean Architecture)

The project follows a strict layered architecture with clear dependency rules:

- **API Layer** (`app/api/`): Thin route handlers that validate input via Pydantic schemas and delegate to services. No business logic lives here.
- **Service Layer** (`app/domain/services/`): All business rules and orchestration. Services depend on repositories (abstractions), not on the database directly.
- **Infrastructure Layer** (`app/infrastructure/`): Repository implementations that translate between domain models and the database. Swappable for testing.
- **Domain Layer** (`app/domain/`): ORM models and Pydantic schemas. No dependencies on infrastructure or API concerns.

### 2. Repository Pattern

Repositories abstract data access behind a clean interface. This:
- Makes the service layer testable without a real database
- Allows swapping storage backends (PostgreSQL, SQLite for tests)
- Centralizes query logic

### 3. Dependency Injection

FastAPI's built-in DI system wires everything together:
- `get_db()` provides an async database session per request
- `get_product_service()` creates a service with its repository
- The `Container` class in `app/core/dependencies.py` provides factory methods

### 4. Configuration Management

Layered configuration with clear precedence:
1. **YAML files** (`config/*.yaml`): Environment-specific defaults
2. **Environment variables**: Override specific values (e.g., `DATABASE_URL`)
3. **Pydantic Settings**: Validates all config at startup

### 5. Structured Logging

Uses `structlog` for JSON-formatted logs with:
- Timestamps, log levels, and caller information
- Context variable binding for request IDs
- Console output in development, JSON in production

### 6. OpenTelemetry

All components are instrumented for observability:
- FastAPI request tracing
- SQLAlchemy query tracing
- Redis command tracing
- OTLP export to collector/backend of choice

### 7. State Machine for Orders

Order status transitions follow a strict state machine:
```
pending → confirmed → processing → shipped → delivered
   ↓          ↓           ↓           ↓
cancelled   cancelled   cancelled   cancelled → refunded
```

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- Docker and Docker Compose (for full stack)

### Local Development

```bash
# Clone and enter the project
cd amazon

# Copy environment file
cp .env.example .env

# Create virtual environment and install dependencies
uv venv
uv pip install -e ".[dev]"

# Run database migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --reload
```

### Using Docker Compose

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f app

# Run migrations
docker compose exec app alembic upgrade head
```

### Run Tests

```bash
# All tests
pytest -v

# With coverage
pytest --cov=app --cov-report=term-missing

# Specific test file
pytest tests/test_products.py -v
```

### Lint and Type Check

```bash
# Ruff linter
ruff check app/ tests/

# Ruff formatter
ruff format app/ tests/

# Mypy type checker
mypy app/ tests/
```

## API Endpoints

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health/live` | Liveness probe |
| GET | `/api/v1/health/ready` | Readiness probe (checks DB + Redis) |

### Products

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/products/` | Create a product |
| GET | `/api/v1/products/` | List products (paginated) |
| GET | `/api/v1/products/{id}` | Get a product by ID |
| PATCH | `/api/v1/products/{id}` | Update a product |
| DELETE | `/api/v1/products/{id}` | Delete a product |

### Orders

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/orders/` | Create an order |
| GET | `/api/v1/orders/` | List orders (paginated) |
| GET | `/api/v1/orders/{id}` | Get an order by ID |
| PATCH | `/api/v1/orders/{id}/status` | Update order status |
| POST | `/api/v1/orders/{id}/cancel` | Cancel an order |

## Project Structure

```
amazon/
├── app/
│   ├── api/v1/           # API routes (health, products, orders)
│   ├── config/            # Pydantic settings + YAML loading
│   ├── core/              # Database, Redis, logging, telemetry, DI
│   ├── domain/
│   │   ├── models/        # SQLAlchemy ORM models
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   └── services/      # Business logic
│   └── infrastructure/
│       └── repositories/  # Data access layer
├── alembic/               # Database migrations
├── config/                # YAML environment configs
├── docker/                # Dockerfile, entrypoint, OTEL config
├── tests/                 # Unit tests
├── .github/workflows/     # CI pipeline
├── docker-compose.yml     # Full stack orchestration
└── pyproject.toml         # Project metadata and tooling config
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | Environment name |
| `APP_DEBUG` | `true` | Enable debug mode |
| `APP_LOG_LEVEL` | `DEBUG` | Logging level |
| `APP_SECRET_KEY` | — | Application secret key |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `SERVER_HOST` | `0.0.0.0` | Server bind address |
| `SERVER_PORT` | `8000` | Server port |
| `OTEL_SERVICE_NAME` | `amazon` | OpenTelemetry service name |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP exporter endpoint |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Runtime | Python 3.12 |
| Web Framework | FastAPI |
| Database | PostgreSQL 16 (async via asyncpg) |
| Cache | Redis 7 |
| ORM | SQLAlchemy 2.x (async) |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Configuration | Pydantic Settings + YAML |
| Logging | structlog (structured JSON) |
| Observability | OpenTelemetry |
| Testing | pytest, pytest-asyncio, httpx |
| Linting | ruff |
| Type Checking | mypy (strict mode) |
| Packaging | uv |
| Containerization | Docker, Docker Compose |
| CI/CD | GitHub Actions |
