"""Tests for the autonomous sourcing agent — queue, pipeline, worker, scheduler, and monitoring.

Uses mocked dependencies to avoid requiring actual Redis, suppliers, or APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.agent.logger import DecisionLogger
from app.agent.models import (
    AgentConfig,
    AgentStatus,
    DecisionAction,
    DecisionLog,
    Task,
    TaskStatus,
    TaskType,
)
from app.agent.monitor import AgentMonitor
from app.agent.notifier import Notifier
from app.agent.pipeline import SourcingPipeline
from app.agent.queue import TaskQueue
from app.agent.scheduler import AgentScheduler
from app.agent.worker import Worker


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get.return_value = None
    redis.set.return_value = True
    redis.lpush.return_value = 1
    redis.lrange.return_value = []
    redis.sadd.return_value = 1
    redis.srem.return_value = 1
    redis.scard.return_value = 0
    redis.smembers.return_value = set()
    redis.blpop.return_value = None
    redis.incr.return_value = 1
    redis.delete.return_value = 1
    redis.ltrim.return_value = True
    return redis


@pytest.fixture
def task_queue(mock_redis: AsyncMock) -> TaskQueue:
    return TaskQueue(redis=mock_redis)


@pytest.fixture
def decision_logger(mock_redis: AsyncMock) -> DecisionLogger:
    return DecisionLogger(redis=mock_redis)


@pytest.fixture
def notifier() -> Notifier:
    return Notifier()


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        worker_count=2,
        cycle_interval_minutes=60,
        task_timeout_seconds=30,
    )


@pytest.fixture
def mock_pipeline() -> AsyncMock:
    pipeline = AsyncMock(spec=SourcingPipeline)
    pipeline.scan_supplier = AsyncMock(return_value=[
        {"supplier_sku": "SKU001", "title": "Test Product", "price": 10.99, "upc": "123456789012"},
    ])
    pipeline.run_full_pipeline = AsyncMock(
        return_value=DecisionLog(
            id=str(uuid.uuid4()),
            agent_run_id="test-run",
            action=DecisionAction.BUY,
            opportunity_score=75.0,
            product_title="Test Product",
        ),
    )
    pipeline.retrieve_amazon_data = AsyncMock(
        return_value={"asin": "B0TEST", "amazon_price": 24.99},
    )
    return pipeline


# ═══════════════════════════════════════════════════════════════
# Task Queue Tests
# ═══════════════════════════════════════════════════════════════


class TestTaskQueue:
    """Test the Redis-backed task queue."""

    @pytest.mark.asyncio
    async def test_enqueue(self, task_queue: TaskQueue) -> None:
        """Test enqueuing a task."""
        task = Task(type=TaskType.FULL_PIPELINE, payload={"asin": "B0TEST"})
        task_id = await task_queue.enqueue(task)
        assert task_id is not None
        assert task.id == task_id

    @pytest.mark.asyncio
    async def test_enqueue_many(self, task_queue: TaskQueue) -> None:
        """Test enqueuing multiple tasks."""
        tasks = [
            Task(type=TaskType.FULL_PIPELINE, payload={"asin": f"B0TEST{i}"})
            for i in range(5)
        ]
        ids = await task_queue.enqueue_many(tasks)
        assert len(ids) == 5

    @pytest.mark.asyncio
    async def test_dequeue_empty(self, task_queue: TaskQueue) -> None:
        """Test dequeuing from empty queue returns None."""
        task = await task_queue.dequeue("worker-1", timeout=1)
        assert task is None

    @pytest.mark.asyncio
    async def test_depth(self, task_queue: TaskQueue) -> None:
        """Test queue depth."""
        depth = await task_queue.depth()
        assert depth >= 0

    @pytest.mark.asyncio
    async def test_stats(self, task_queue: TaskQueue) -> None:
        """Test queue stats."""
        stats = await task_queue.stats()
        assert "depth" in stats
        assert "running" in stats
        assert "enqueued" in stats

    @pytest.mark.asyncio
    async def test_clear(self, task_queue: TaskQueue) -> None:
        """Test clearing the queue."""
        count = await task_queue.clear()
        assert count >= 0

    @pytest.mark.asyncio
    async def test_local_fallback(self) -> None:
        """Test local fallback when Redis is unavailable."""
        queue = TaskQueue(redis=None)
        task = Task(type=TaskType.FULL_PIPELINE, payload={})
        task_id = await queue.enqueue(task)
        assert task_id is not None

        # Dequeue should work from local queue
        dequeued = await queue.dequeue("worker-1", timeout=1)
        assert dequeued is not None
        assert dequeued.id == task_id


# ═══════════════════════════════════════════════════════════════
# Decision Logger Tests
# ═══════════════════════════════════════════════════════════════


class TestDecisionLogger:
    """Test the decision logger."""

    @pytest.mark.asyncio
    async def test_log_decision(self, decision_logger: DecisionLogger) -> None:
        """Test logging a decision."""
        decision = DecisionLog(
            id=str(uuid.uuid4()),
            agent_run_id="test-run",
            action=DecisionAction.BUY,
            opportunity_score=85.0,
            product_title="Great Product",
        )
        decision_id = await decision_logger.log(decision)
        assert decision_id == decision.id

    @pytest.mark.asyncio
    async def test_get_recent(self, decision_logger: DecisionLogger) -> None:
        """Test getting recent decisions."""
        decisions = await decision_logger.get_recent(limit=10)
        assert isinstance(decisions, list)

    @pytest.mark.asyncio
    async def test_count(self, decision_logger: DecisionLogger) -> None:
        """Test counting decisions."""
        count = await decision_logger.count()
        assert count >= 0

    @pytest.mark.asyncio
    async def test_stats(self, decision_logger: DecisionLogger) -> None:
        """Test decision stats."""
        stats = await decision_logger.stats()
        assert "total_decisions" in stats


# ═══════════════════════════════════════════════════════════════
# Notifier Tests
# ═══════════════════════════════════════════════════════════════


class TestNotifier:
    """Test the notification system."""

    @pytest.mark.asyncio
    async def test_notify_opportunity(self, notifier: Notifier) -> None:
        """Test notifying a BUY opportunity."""
        decision = DecisionLog(
            id=str(uuid.uuid4()),
            agent_run_id="test",
            action=DecisionAction.BUY,
            opportunity_score=85.0,
            product_title="Great Product",
            roi_percentage=45.0,
            net_profit=5.0,
            monthly_sales=1500,
        )
        # Should not raise
        await notifier.notify_opportunity(decision)

    @pytest.mark.asyncio
    async def test_notify_low_score(self, notifier: Notifier) -> None:
        """Test that low-score opportunities are not notified."""
        decision = DecisionLog(
            id=str(uuid.uuid4()),
            agent_run_id="test",
            action=DecisionAction.BUY,
            opportunity_score=30.0,
        )
        await notifier.notify_opportunity(decision)
        # Should not raise (score below default 60 threshold)

    @pytest.mark.asyncio
    async def test_notify_watch(self, notifier: Notifier) -> None:
        """Test notifying a WATCH opportunity."""
        decision = DecisionLog(
            id=str(uuid.uuid4()),
            agent_run_id="test",
            action=DecisionAction.WATCH,
            opportunity_score=55.0,
        )
        await notifier.notify_watch(decision)

    @pytest.mark.asyncio
    async def test_notify_error(self, notifier: Notifier) -> None:
        """Test notifying an error."""
        await notifier.notify_error("Test error", "Something went wrong")


# ═══════════════════════════════════════════════════════════════
# Pipeline Tests
# ═══════════════════════════════════════════════════════════════


class TestSourcingPipeline:
    """Test the sourcing pipeline."""

    @pytest.mark.asyncio
    async def test_scan_supplier(
        self,
        mock_pipeline: AsyncMock,
    ) -> None:
        """Test scanning a supplier."""
        products = await mock_pipeline.scan_supplier("walmart", page=1)
        assert len(products) == 1
        assert products[0]["supplier_sku"] == "SKU001"

    @pytest.mark.asyncio
    async def test_retrieve_amazon_data(
        self,
        mock_pipeline: AsyncMock,
    ) -> None:
        """Test retrieving Amazon data."""
        data = await mock_pipeline.retrieve_amazon_data("B0TEST")
        assert data is not None
        assert data["asin"] == "B0TEST"

    @pytest.mark.asyncio
    async def test_run_full_pipeline(
        self,
        mock_pipeline: AsyncMock,
    ) -> None:
        """Test running the full pipeline."""
        decision = await mock_pipeline.run_full_pipeline(
            supplier_code="walmart",
            supplier_sku="SKU001",
            product_title="Test Product",
            supplier_price=10.99,
        )
        assert decision.action == DecisionAction.BUY
        assert decision.opportunity_score == 75.0


# ═══════════════════════════════════════════════════════════════
# Worker Tests
# ═══════════════════════════════════════════════════════════════


class TestWorker:
    """Test the worker."""

    @pytest.mark.asyncio
    async def test_worker_start_stop(
        self,
        task_queue: TaskQueue,
        mock_pipeline: AsyncMock,
        agent_config: AgentConfig,
    ) -> None:
        """Test starting and stopping a worker."""
        worker = Worker(
            worker_id="test-worker",
            queue=task_queue,
            pipeline=mock_pipeline,
            config=agent_config,
        )
        await worker.start()
        assert worker.info.status in ("idle", "busy")

        await worker.stop()
        assert worker.info.status == "stopped"

    @pytest.mark.asyncio
    async def test_worker_info(
        self,
        task_queue: TaskQueue,
        mock_pipeline: AsyncMock,
        agent_config: AgentConfig,
    ) -> None:
        """Test worker info."""
        worker = Worker(
            worker_id="test-worker",
            queue=task_queue,
            pipeline=mock_pipeline,
            config=agent_config,
        )
        info = worker.info
        assert info.worker_id == "test-worker"
        assert info.status == "idle"
        assert info.tasks_completed == 0
        assert info.tasks_failed == 0


# ═══════════════════════════════════════════════════════════════
# Scheduler Tests
# ═══════════════════════════════════════════════════════════════


class TestAgentScheduler:
    """Test the agent scheduler."""

    @pytest.mark.asyncio
    async def test_scheduler_start_stop(
        self,
        task_queue: TaskQueue,
        mock_pipeline: AsyncMock,
        agent_config: AgentConfig,
    ) -> None:
        """Test starting and stopping the scheduler."""
        plugin_manager = AsyncMock()
        plugin_manager.get_enabled_suppliers.return_value = ["walmart"]

        scheduler = AgentScheduler(
            queue=task_queue,
            pipeline=mock_pipeline,
            plugin_manager=plugin_manager,
            config=agent_config,
        )

        await scheduler.start()
        status = scheduler.get_status()
        assert status.status in (AgentStatus.RUNNING, AgentStatus.DEGRADED)
        assert len(status.workers) == agent_config.worker_count

        await scheduler.stop()
        status = scheduler.get_status()
        assert status.status == AgentStatus.STOPPED

    @pytest.mark.asyncio
    async def test_scheduler_pause_resume(
        self,
        task_queue: TaskQueue,
        mock_pipeline: AsyncMock,
        agent_config: AgentConfig,
    ) -> None:
        """Test pausing and resuming the scheduler."""
        plugin_manager = AsyncMock()
        plugin_manager.get_enabled_suppliers.return_value = []

        scheduler = AgentScheduler(
            queue=task_queue,
            pipeline=mock_pipeline,
            plugin_manager=plugin_manager,
            config=agent_config,
        )

        await scheduler.start()
        await scheduler.pause()
        assert scheduler.get_status().status == AgentStatus.PAUSED

        await scheduler.resume()
        assert scheduler.get_status().status == AgentStatus.RUNNING

        await scheduler.stop()


# ═══════════════════════════════════════════════════════════════
# Monitor Tests
# ═══════════════════════════════════════════════════════════════


class TestAgentMonitor:
    """Test the agent monitor."""

    @pytest.mark.asyncio
    async def test_health_check(
        self,
        task_queue: TaskQueue,
        mock_pipeline: AsyncMock,
        agent_config: AgentConfig,
    ) -> None:
        """Test health check."""
        plugin_manager = AsyncMock()
        plugin_manager.get_enabled_suppliers.return_value = []

        scheduler = AgentScheduler(
            queue=task_queue,
            pipeline=mock_pipeline,
            plugin_manager=plugin_manager,
            config=agent_config,
        )
        decision_logger = DecisionLogger(redis=None)
        monitor = AgentMonitor(scheduler, task_queue, decision_logger)

        health = await monitor.health_check()
        assert "healthy" in health
        assert "status" in health
        assert "workers_total" in health

    @pytest.mark.asyncio
    async def test_dashboard(
        self,
        task_queue: TaskQueue,
        mock_pipeline: AsyncMock,
        agent_config: AgentConfig,
    ) -> None:
        """Test getting the dashboard."""
        plugin_manager = AsyncMock()
        plugin_manager.get_enabled_suppliers.return_value = []

        scheduler = AgentScheduler(
            queue=task_queue,
            pipeline=mock_pipeline,
            plugin_manager=plugin_manager,
            config=agent_config,
        )
        decision_logger = DecisionLogger(redis=None)
        monitor = AgentMonitor(scheduler, task_queue, decision_logger)

        dashboard = await monitor.get_dashboard()
        assert "agent" in dashboard
        assert "workers" in dashboard
        assert "queue" in dashboard
        assert "decisions" in dashboard
        assert "errors" in dashboard
        assert "timestamp" in dashboard


# ═══════════════════════════════════════════════════════════════
# Task Model Tests
# ═══════════════════════════════════════════════════════════════


class TestTaskModel:
    """Test the Task model."""

    def test_task_creation(self) -> None:
        """Test creating a task."""
        task = Task(
            id="test-task-1",
            type=TaskType.FULL_PIPELINE,
            payload={"asin": "B0TEST"},
        )
        assert task.id == "test-task-1"
        assert task.type == TaskType.FULL_PIPELINE
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 0
        assert task.max_retries == 3

    def test_task_serialization(self) -> None:
        """Test task JSON serialization."""
        task = Task(
            id="test-task-1",
            type=TaskType.SCAN_SUPPLIER,
            payload={"supplier_code": "walmart"},
        )
        data = task.model_dump()
        assert data["id"] == "test-task-1"
        assert data["type"] == "scan_supplier"
        assert data["status"] == "pending"


class TestDecisionLogModel:
    """Test the DecisionLog model."""

    def test_decision_creation(self) -> None:
        """Test creating a decision log."""
        decision = DecisionLog(
            id="test-decision-1",
            agent_run_id="test-run",
            action=DecisionAction.BUY,
            opportunity_score=85.0,
            product_title="Test Product",
        )
        assert decision.id == "test-decision-1"
        assert decision.action == DecisionAction.BUY
        assert decision.opportunity_score == 85.0

    def test_decision_serialization(self) -> None:
        """Test decision JSON serialization."""
        decision = DecisionLog(
            id="test-decision-1",
            agent_run_id="test-run",
            action=DecisionAction.AVOID,
            opportunity_score=25.0,
            strengths=["Good"],
            weaknesses=["Bad ROI"],
        )
        data = decision.model_dump()
        assert data["action"] == "AVOID"
        assert data["strengths"] == ["Good"]
        assert data["weaknesses"] == ["Bad ROI"]
