"""OpenTelemetry tracing setup for manor services.

`configure_telemetry()` is a lazy, idempotent singleton (mirrors
`manor.logger.configure_logging`). It is a NO-OP unless
`OTEL_EXPORTER_OTLP_ENDPOINT` is set, so local/dev without a collector simply
runs untraced. OTel is the single tracer — ddtrace auto-instrumentation is
disabled at the service entrypoints, so nothing double-patches httpx/fastapi.
"""

from __future__ import annotations

import logging
import os
import threading

__all__ = ["configure_telemetry"]

_lock = threading.Lock()
_configured = False
_log = logging.getLogger(__name__)


def configure_telemetry(app=None, *, service_name: str | None = None, engine=None) -> bool:
    """Set up the global OTel tracer + auto-instrumentation. Idempotent.

    Returns True if tracing was configured, False if skipped (no endpoint).
    - app: FastAPI/Starlette app to instrument for server spans (optional).
    - service_name: resource `service.name`; falls back to OTEL_SERVICE_NAME,
      then DD_SERVICE, then "manor-service".
    - engine: a SQLAlchemy Engine (or AsyncEngine.sync_engine) to instrument
      for DB spans (optional).
    """
    global _configured
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        _log.info("otel: OTEL_EXPORTER_OTLP_ENDPOINT unset — tracing disabled")
        return False

    with _lock:
        if _configured:
            return True

        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased

        name = (
            service_name
            or os.getenv("OTEL_SERVICE_NAME")
            or os.getenv("DD_SERVICE")
            or "manor-service"
        )
        resource = Resource.create(
            {
                "service.name": name,
                "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            }
        )
        ratio = os.getenv("OTEL_TRACES_SAMPLER_ARG")
        sampler = ParentBased(TraceIdRatioBased(float(ratio))) if ratio else ParentBased(ALWAYS_ON)

        provider = TracerProvider(resource=resource, sampler=sampler)
        # OTLPSpanExporter reads OTEL_EXPORTER_OTLP_ENDPOINT itself and POSTs to
        # {endpoint}/v1/traces (http/protobuf).
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)

        # httpx covers EVERY outbound client, including the MCP
        # StreamableHttpTransport's httpx client — so `traceparent` is injected
        # on the agents->search hop automatically, no manual header code.
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()

        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)

        if engine is not None:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument(engine=engine)

        _configured = True
        _log.info("otel: tracing configured (service=%s endpoint=%s)", name, endpoint)
        return True
