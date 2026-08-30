"""Tests for the dev-only, opt-in OTLP log export helper.

The most important guarantee here is PROD SAFETY: with ``OTEL_LOGS_EXPORTER``
unset (the production configuration — prod DOES set
``OTEL_EXPORTER_OTLP_ENDPOINT`` for traces, but NEVER sets
``OTEL_LOGS_EXPORTER``), the helper is a strict no-op and attaches no handler to
the root logger. That is the acceptance gate.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk._logs import LoggingHandler

from manor import telemetry

# Patch target for the OTLP log exporter. The helper imports it lazily inside the
# function body, so patching the source module's attribute intercepts it and keeps
# the tests fully offline (no real /v1/logs POST, no live exporter connection).
_EXPORTER_PATH = "opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter"


def _otlp_handlers():
    """LoggingHandler instances currently attached to the ROOT stdlib logger."""
    return [h for h in logging.getLogger().handlers if isinstance(h, LoggingHandler)]


@pytest.fixture(autouse=True)
def reset_otlp_logging_state():
    """Reset the module singleton and strip any OTLP handler this test attached."""
    telemetry._logs_configured = False
    before = list(logging.getLogger().handlers)
    yield
    telemetry._logs_configured = False
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, LoggingHandler) and h not in before:
            root.removeHandler(h)


def test_default_is_noop_even_with_endpoint(monkeypatch):
    """PROD SAFETY: OTEL_LOGS_EXPORTER unset -> no-op, no handler, endpoint or not."""
    monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    assert telemetry.configure_otlp_logging(service_name="svc") is False
    assert _otlp_handlers() == []


def test_empty_value_is_noop(monkeypatch):
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    assert telemetry.configure_otlp_logging(service_name="svc") is False
    assert _otlp_handlers() == []


def test_wrong_value_is_noop(monkeypatch):
    """OTEL_LOGS_EXPORTER=none (OTel's "disable" sentinel) -> no-op."""
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "none")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    assert telemetry.configure_otlp_logging(service_name="svc") is False
    assert _otlp_handlers() == []


def test_otlp_without_endpoint_is_noop(monkeypatch):
    """Gate needs BOTH flag AND endpoint: flag alone is not enough."""
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    assert telemetry.configure_otlp_logging(service_name="svc") is False
    assert _otlp_handlers() == []


def test_enabled_attaches_handler_once(monkeypatch):
    """Both gate conditions met -> True, exactly one root LoggingHandler, idempotent."""
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    with patch(_EXPORTER_PATH, MagicMock()):
        assert telemetry.configure_otlp_logging(service_name="svc") is True
        # Idempotent: a second call must not add a second handler.
        assert telemetry.configure_otlp_logging(service_name="svc") is True

    assert len(_otlp_handlers()) == 1

    from opentelemetry._logs import get_logger_provider
    from opentelemetry.sdk._logs import LoggerProvider

    assert isinstance(get_logger_provider(), LoggerProvider)


def test_enabled_is_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "  OTLP  ")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    with patch(_EXPORTER_PATH, MagicMock()):
        assert telemetry.configure_otlp_logging(service_name="svc") is True

    assert len(_otlp_handlers()) == 1


def test_no_arg_resolves_otel_service_name_over_dd(monkeypatch):
    """With no explicit arg (exactly how configure_logging now calls it), the OTLP
    logs resource resolves OTEL_SERVICE_NAME — the traces' service.name — NOT the
    Datadog-legacy DD_SERVICE. This keeps the Python services under `service-…`
    (not `manor-service-…`) so the dashboards' `service-…` filter matches them."""
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "service-agents")
    monkeypatch.setenv("DD_SERVICE", "manor-service-agents")

    from opentelemetry.sdk.resources import Resource

    captured = {}
    real_create = Resource.create

    def spy(attributes=None, *args, **kwargs):
        captured.update(attributes or {})
        return real_create(attributes, *args, **kwargs)

    monkeypatch.setattr(Resource, "create", spy)
    with patch(_EXPORTER_PATH, MagicMock()):
        assert telemetry.configure_otlp_logging() is True

    assert captured.get("service.name") == "service-agents"


def test_configure_logging_invokes_helper(monkeypatch):
    """configure_logging() must call the helper (wired in after basicConfig)."""
    import structlog

    import manor.logger.structured_logger as sl

    # Reset the logging singleton so configure_logging() actually runs its body.
    sl._is_configured = False
    sl._logger_instance = None
    structlog.reset_defaults()

    called = MagicMock(return_value=False)
    with patch("manor.telemetry.configure_otlp_logging", called):
        sl.configure_logging(service="wiring-test", env="cicd")

    # Must be called with NO service_name — feeding the DD-derived service (here
    # "wiring-test") would shadow OTEL_SERVICE_NAME in the OTLP logs resource.
    called.assert_called_once_with()
