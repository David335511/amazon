"""Structured logging configuration using structlog.

Design decisions:
- structlog provides structured, JSON-formatted logs by default.
- Pre-configured processors add timestamps, call site info, and stack traces.
- Log level is driven by configuration (YAML + env var).
- A `get_logger` convenience function returns a bound logger with consistent metadata.
- OpenTelemetry correlation IDs can be injected via context vars.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog

from app.config import settings


def configure_logging() -> None:
    """Configure structlog processors and standard library logging.

    Must be called once at application startup, before any loggers are used.
    """
    log_level = getattr(logging, settings.logging.level.upper(), logging.INFO)

    # Shared processors
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.logging.format == "json":
        # JSON output for production log aggregation
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        # Console-friendly output for development
        renderer = structlog.dev.ConsoleRenderer(
            sort_keys=False,
            colors=True,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                },
            ),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging to use structlog
    handler: logging.Handler
    handlers: list[logging.Handler] = []

    # Console handler
    if "console" in settings.logging.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        handlers.append(handler)

    # File handler
    if "file" in settings.logging.handlers and settings.logging.file_path:
        log_path = Path(settings.logging.file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_path),
            when=settings.logging.rotation or "midnight",
            backupCount=30,
            encoding="utf-8",
        )
        handler.setLevel(log_level)
        handlers.append(handler)

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    for h in handlers:
        h.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    for h in handlers:
        root_logger.addHandler(h)

    # Suppress noisy third-party loggers
    for logger_name in ("uvicorn.access", "uvicorn.error", "httpx"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str | None = None, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Get a bound structlog logger.

    Args:
        name: Logger name (typically __name__). Defaults to 'amazon'.
        **initial_values: Key-value pairs to bind to all log messages.

    Returns:
        A bound structlog logger.
    """
    return structlog.get_logger(name or "amazon", **initial_values)  # type: ignore[no-any-return]
