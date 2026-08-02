"""Data models for the autonomous sourcing agent.

Design decisions:
- Task models capture the full lifecycle of a sourcing operation.
- DecisionLog is append-only — every decision is recorded for audit.
- WorkerStatus enables real-time monitoring of the agent fleet.
- All timestamps are UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════


class TaskType(str, Enum):
    """Types of tasks the agent can process."""

    SCAN_SUPPLIER = "scan_supplier"           # Scan a supplier for new products
    RETRIEVE_AMAZON = "retrieve_amazon"       # Retrieve Amazon data for a product
    CALCULATE_PROFIT = "calculate_profit"     # Calculate profit for a product
    SCORE_OPPORTUNITY = "score_opportunity"   # Score and evaluate a product
    GENERATE_RECOMMENDATION = "generate_recommendation"  # AI recommendation
    FULL_PIPELINE = "full_pipeline"           # Run the full pipeline for a product
    SUPPLIER_CYCLE = "supplier_cycle"         # Complete cycle for one supplier


class TaskStatus(str, Enum):
    """Status of a task in the queue."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class AgentStatus(str, Enum):
    """Status of the agent system."""

    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    DEGRADED = "degraded"  # Some workers failing
    ERROR = "error"


class DecisionAction(str, Enum):
    """The action taken by the agent for a product."""

    BUY = "BUY"
    WATCH = "WATCH"
    AVOID = "AVOID"
    SKIP = "SKIP"           # Insufficient data to decide
    ERROR = "ERROR"         # Error during evaluation


# ═══════════════════════════════════════════════════════════════
# Task Models
# ═══════════════════════════════════════════════════════════════


class Task(BaseModel):
    """A unit of work for the agent."""

    id: str = Field(
        default_factory=lambda: "", description="Unique task ID (auto-generated if empty)",
    )
    type: TaskType = Field(..., description="Type of task")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current status")
    priority: int = Field(default=0, ge=0, le=10, description="Priority (0=lowest, 10=highest)")
    retry_count: int = Field(default=0, ge=0, description="Number of retries so far")
    max_retries: int = Field(default=3, ge=0, description="Maximum retries before giving up")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="When created")
    started_at: datetime | None = Field(None, description="When processing started")
    completed_at: datetime | None = Field(None, description="When processing completed")
    worker_id: str | None = Field(None, description="Worker processing this task")

    # Task payload
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Task-specific data (supplier_code, asin, product_id, etc.)",
    )
    result: dict[str, Any] | None = Field(
        None, description="Task result data",
    )
    error: str | None = Field(None, description="Error message if failed")


# ═══════════════════════════════════════════════════════════════
# Decision Log
# ═══════════════════════════════════════════════════════════════


class DecisionLog(BaseModel):
    """Immutable record of a sourcing decision made by the agent."""

    id: str = Field(..., description="Unique decision ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="When decision was made")
    agent_run_id: str = Field(..., description="Agent run identifier")

    # Product
    asin: str | None = Field(None, description="Amazon ASIN")
    supplier_code: str | None = Field(None, description="Supplier code")
    supplier_sku: str | None = Field(None, description="Supplier SKU")
    product_title: str | None = Field(None, description="Product title")

    # Decision
    action: DecisionAction = Field(..., description="Action taken")
    opportunity_score: float | None = Field(None, description="Opportunity score 0-100")
    confidence: str | None = Field(None, description="Confidence level")
    risk_level: str | None = Field(None, description="Risk level")
    recommendation: str | None = Field(None, description="AI recommendation (BUY/WATCH/AVOID)")

    # Metrics
    roi_percentage: float | None = Field(None, description="ROI percentage")
    net_profit: float | None = Field(None, description="Net profit per unit")
    monthly_sales: int | None = Field(None, description="Estimated monthly sales")
    amazon_price: float | None = Field(None, description="Amazon price")
    supplier_price: float | None = Field(None, description="Supplier price")

    # Reasoning
    strengths: list[str] = Field(default_factory=list, description="Key strengths")
    weaknesses: list[str] = Field(default_factory=list, description="Key weaknesses")
    risks: list[str] = Field(default_factory=list, description="Identified risks")
    explanation: str | None = Field(None, description="Natural language explanation")

    # Audit
    pipeline_duration_ms: float | None = Field(None, description="Total pipeline duration")
    data_points_used: int = Field(default=0, description="Data points used in evaluation")
    error: str | None = Field(None, description="Error if decision failed")


# ═══════════════════════════════════════════════════════════════
# Worker & Agent Status
# ═══════════════════════════════════════════════════════════════


class WorkerInfo(BaseModel):
    """Information about a running worker."""

    worker_id: str = Field(..., description="Unique worker ID")
    status: str = Field(default="idle", description="idle, busy, error, stopped")
    current_task_id: str | None = Field(None, description="Task currently being processed")
    current_task_type: str | None = Field(None, description="Type of current task")
    tasks_completed: int = Field(default=0, description="Tasks completed")
    tasks_failed: int = Field(default=0, description="Tasks failed")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="When worker started")
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Last heartbeat")
    uptime_seconds: float = Field(default=0, description="Uptime in seconds")


class AgentRunInfo(BaseModel):
    """Information about the current agent run."""

    run_id: str = Field(..., description="Unique run ID")
    status: AgentStatus = Field(default=AgentStatus.STOPPED, description="Agent status")
    started_at: datetime | None = Field(None, description="When the agent started")
    stopped_at: datetime | None = Field(None, description="When the agent stopped")
    workers: list[WorkerInfo] = Field(default_factory=list, description="Active workers")
    total_tasks_processed: int = Field(default=0, description="Total tasks processed")
    total_tasks_succeeded: int = Field(default=0, description="Tasks succeeded")
    total_tasks_failed: int = Field(default=0, description="Tasks failed")
    total_decisions_made: int = Field(default=0, description="Decisions logged")
    queue_depth: int = Field(default=0, description="Current queue depth")
    cycle_count: int = Field(default=0, description="Number of complete cycles run")
    last_cycle_at: datetime | None = Field(None, description="Last cycle completion time")
    errors: list[str] = Field(default_factory=list, description="Recent errors")


class AgentConfig(BaseModel):
    """Configuration for the autonomous agent."""

    # Worker pool
    worker_count: int = Field(default=3, ge=1, le=20, description="Number of concurrent workers")
    task_timeout_seconds: int = Field(default=120, ge=10, le=600, description="Task timeout")

    # Scheduling
    cycle_interval_minutes: int = Field(
        default=60, ge=5, le=1440,
        description="Time between full supplier cycles",
    )
    scan_page_size: int = Field(default=20, ge=1, le=100, description="Products per supplier scan page")

    # Retry
    max_retries_per_task: int = Field(default=3, ge=0, le=10, description="Max retries per task")
    retry_base_delay_seconds: int = Field(default=10, ge=1, description="Base delay between retries")

    # Pipeline stages (enable/disable)
    enable_supplier_scan: bool = Field(default=True, description="Scan suppliers for products")
    enable_amazon_retrieval: bool = Field(default=True, description="Retrieve Amazon data")
    enable_profit_calculation: bool = Field(default=True, description="Calculate profit")
    enable_scoring: bool = Field(default=True, description="Score opportunities")
    enable_ai_reasoning: bool = Field(default=True, description="Generate AI recommendations")
    enable_notifications: bool = Field(default=True, description="Send notifications")

    # Thresholds
    min_opportunity_score_to_notify: float = Field(
        default=60.0, ge=0, le=100,
        description="Minimum score to trigger a notification",
    )
    max_products_per_supplier_per_cycle: int = Field(
        default=50, ge=1, le=500,
        description="Max products to process per supplier per cycle",
    )

    # Monitoring
    heartbeat_interval_seconds: int = Field(default=30, ge=5, description="Worker heartbeat interval")
    log_retention_days: int = Field(default=90, ge=1, description="Days to retain decision logs")
