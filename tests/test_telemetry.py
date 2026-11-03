import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from opentelemetry.util._once import Once

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


@pytest.fixture
def span_exporter(monkeypatch):
    """configure_telemetry with its OTLP exporter swapped for an in-memory one."""
    _reset()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    # The global tracer provider can be set once per process; give this test its own.
    monkeypatch.setattr(trace, "_TRACER_PROVIDER_SET_ONCE", Once())
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None)
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
        lambda: exporter,
    )
    yield exporter
    _reset()


async def test_streaming_route_records_no_send_or_receive_spans(span_exporter):
    chunks, interval_s = 5, 0.05
    stream_ns = {}

    async def body():
        stream_ns["start"] = time.time_ns()
        for i in range(chunks):
            yield f"chunk {i}\n"
            await asyncio.sleep(interval_s)
        stream_ns["end"] = time.time_ns()

    app = FastAPI()

    @app.post("/stream")
    async def stream(request: Request):
        await request.body()
        return StreamingResponse(body(), media_type="text/plain")

    assert telemetry.configure_telemetry(app, service_name="svc") is True

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/stream", json={"q": "x"})
    assert response.status_code == 200
    assert response.text.count("chunk") == chunks

    trace.get_tracer_provider().force_flush()
    spans = span_exporter.get_finished_spans()
    names = [s.name for s in spans]

    assert not [n for n in names if n.endswith((" http send", " http receive"))], names

    (server,) = [s for s in spans if s.kind is SpanKind.SERVER]
    attrs = server.attributes
    assert attrs.get("http.response.status_code", attrs.get("http.status_code")) == 200
    # The server span still covers the whole stream.
    assert server.start_time <= stream_ns["start"]
    assert server.end_time >= stream_ns["end"]
