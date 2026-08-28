from manor import telemetry


def _reset():
    telemetry._configured = False


def test_no_endpoint_is_noop(monkeypatch):
    _reset()
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert telemetry.configure_telemetry(service_name="svc") is False


def test_configures_once_with_endpoint(monkeypatch):
    _reset()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    assert telemetry.configure_telemetry(service_name="svc") is True
    # idempotente: segunda chamada não reconfigura, retorna True
    assert telemetry.configure_telemetry(service_name="svc") is True
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    assert isinstance(trace.get_tracer_provider(), TracerProvider)
