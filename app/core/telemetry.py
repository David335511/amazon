"""OpenTelemetry instrumentation setup.

Design decisions:
- OpenTelemetry is configured at startup if enabled in settings.
- FastAPI, SQLAlchemy, and Redis are instrumented automatically.
- Resource attributes include service name and deployment environment.
- The SDK is configured with a batch span processor for performance.
- All instrumentation is optional and controlled by feature flags.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio, TraceIdRatioBased

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _parse_otlp_headers(raw: str) -> dict[str, str]:
    """Parse an OTLP header string of comma-separated ``key=value`` pairs."""
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        if not pair.strip():
            continue
        key, sep, value = pair.partition("=")
        if sep and key.strip():
            headers[key.strip()] = value.strip()
    return headers


def configure_telemetry(app: FastAPI) -> None:
    """Configure OpenTelemetry for the FastAPI application.

    Sets up the tracer provider, span processors, and instrumentations.
    Safe to call even if telemetry is disabled (no-op in that case).

    Args:
        app: The FastAPI application instance to instrument.
    """
    if not settings.telemetry.enabled:
        logger.info("OpenTelemetry is disabled")
        return

    # Create resource with service metadata
    resource = Resource.create(
        attributes={
            "service.name": settings.telemetry.service_name,
            "service.version": "0.1.0",
            "deployment.environment": settings.app.log_level.lower(),
        },
    )

    # Configure sampler
    sampler: Any
    if settings.telemetry.traces_sampler == "parentbased_always_on":
        sampler = ParentBasedTraceIdRatio(1.0)
    elif settings.telemetry.traces_sampler == "parentbased_always_off":
        sampler = ParentBasedTraceIdRatio(0.0)
    else:
        sampler = ParentBasedTraceIdRatio(TraceIdRatioBased(0.1))  # type: ignore[arg-type]

    # Create tracer provider
    tracer_provider = TracerProvider(resource=resource, sampler=sampler)

    # Add OTLP span exporter if endpoint is configured
    if settings.telemetry.exporter_otlp_endpoint:
        endpoint = settings.telemetry.exporter_otlp_endpoint
        # Use TLS for https endpoints (e.g. hosted collectors); plaintext otherwise.
        insecure = not endpoint.lower().startswith("https")
        otlp_exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=_parse_otlp_headers(settings.telemetry.exporter_otlp_headers) or None,
            insecure=insecure,
        )
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)

    # Set the global tracer provider
    trace.set_tracer_provider(tracer_provider)

    # Instrument FastAPI
    if settings.telemetry.instrument_fastapi:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
        logger.info("FastAPI instrumented for OpenTelemetry")

    # Instrument SQLAlchemy
    if settings.telemetry.instrument_sqlalchemy:
        SQLAlchemyInstrumentor().instrument()
        logger.info("SQLAlchemy instrumented for OpenTelemetry")

    # Instrument Redis
    if settings.telemetry.instrument_redis:
        RedisInstrumentor().instrument()
        logger.info("Redis instrumented for OpenTelemetry")

    logger.info(
        "OpenTelemetry configured",
        service_name=settings.telemetry.service_name,
        sampler=settings.telemetry.traces_sampler,
    )
