"""OpenTelemetry tracing setup for manor services.

`configure_telemetry()` is a lazy, idempotent singleton (mirrors
`manor.logger.configure_logging`). It is a NO-OP unless
`OTEL_EXPORTER_OTLP_ENDPOINT` is set, so local/dev without a collector simply
runs untraced. OTel is the single tracer — ddtrace auto-instrumentation is
disabled at the service entrypoints, so nothing double-patches httpx/fastapi.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading

__all__ = ["configure_telemetry", "configure_otlp_logging"]

_lock = threading.Lock()
_configured = False

# Separate singleton state for the OTLP log-export path — it is gated on a
# DIFFERENT env var (OTEL_LOGS_EXPORTER) than tracing, so it must be independently
# configurable and idempotent.
_logs_lock = threading.Lock()
_logs_configured = False

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


def configure_otlp_logging(*, service_name: str | None = None) -> bool:
    """Export stdlib log records to an OTLP collector. DEV-ONLY, opt-in. Idempotent.

    STRICT NO-OP by default. This is enabled ONLY when BOTH hold:
      * ``OTEL_LOGS_EXPORTER`` (OpenTelemetry's own env var) equals ``"otlp"``
        (case- and whitespace-insensitive), AND
      * ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set.

    Why a separate flag: production ALREADY sets ``OTEL_EXPORTER_OTLP_ENDPOINT``
    (it points at the prod Alloy gateway for TRACES). Gating log export on the
    endpoint alone would silently turn OTLP logs on in prod and duplicate/interfere
    with the FireLens -> Loki pipeline. Prod never sets ``OTEL_LOGS_EXPORTER``, so
    prod is byte-for-byte unaffected. In dev, ``grafana/otel-lgtm`` ingests logs
    only via OTLP, so setting ``OTEL_LOGS_EXPORTER=otlp`` lights up log export.

    When enabled it builds a ``LoggerProvider`` (same resource fields as
    ``configure_telemetry``), attaches a ``BatchLogRecordProcessor`` wrapping an
    ``OTLPLogExporter`` (which reads ``OTEL_EXPORTER_OTLP_ENDPOINT`` itself and
    POSTs to ``{endpoint}/v1/logs``), sets it as the global logger provider, and
    attaches an OTel ``LoggingHandler`` to the ROOT stdlib logger. That handler
    natively stamps each OTLP log record with the active span's trace_id/span_id,
    so log<->trace correlation works even though the stdlib record body is the
    structlog-rendered JSON string (an accepted simplification).

    Returns True if OTLP log export was configured, False if skipped/failed.
    Never raises: any telemetry failure logs a warning and returns False so it can
    never break application logging.
    """
    global _logs_configured

    # ----- GATE (guard at the very top; strict no-op unless satisfied) -----
    if os.getenv("OTEL_LOGS_EXPORTER", "").strip().lower() != "otlp":
        return False
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False

    with _logs_lock:
        if _logs_configured:
            return True

        try:
            # Import the logs SDK lazily INSIDE the function so the module top-level
            # and the no-op path stay import-cheap.
            from opentelemetry._logs import set_logger_provider
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.sdk.resources import Resource

            # Prefer OTEL_SERVICE_NAME so OTLP logs carry the SAME service.name as the
            # traces (configure_telemetry) and match the dashboards' `service-…` filter.
            # configure_logging passes DD_SERVICE as service_name, but DD_* is Datadog-
            # legacy and on its way out — OTEL_SERVICE_NAME is the source of truth.
            name = (
                os.getenv("OTEL_SERVICE_NAME")
                or service_name
                or os.getenv("DD_SERVICE")
                or "manor-service"
            )
            resource = Resource.create(
                {
                    "service.name": name,
                    "deployment.environment": os.getenv("ENVIRONMENT", "development"),
                }
            )

            provider = LoggerProvider(resource=resource)
            provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
            set_logger_provider(provider)

            handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
            logging.getLogger().addHandler(handler)
            atexit.register(provider.shutdown)

            _logs_configured = True
            _log.info(
                "otel: OTLP log export configured (service=%s endpoint=%s)", name, endpoint
            )
            return True
        except Exception:  # noqa: BLE001 — telemetry must never break app logging
            _log.warning(
                "otel: OTLP log export setup failed; continuing without it", exc_info=True
            )
            return False
