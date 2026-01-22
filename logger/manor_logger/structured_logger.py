"""
Structured logging configuration with Datadog integration.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import sys
import threading
import time
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from typing import Any, Dict, List

import structlog

try:
    from ddtrace import tracer

    DDTRACE_AVAILABLE = True
except ImportError:
    tracer = None
    DDTRACE_AVAILABLE = False

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None
    HTTPX_AVAILABLE = False

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, LOG_LEVEL, logging.INFO)

DD_API_KEY = os.getenv("DD_API_KEY")
DD_SITE = os.getenv("DD_SITE", "us5.datadoghq.com")
DD_SERVICE = os.getenv("DD_SERVICE", "app")
DD_ENV = os.getenv("DD_ENV", os.getenv("ENVIRONMENT", "dev"))

DD_INTAKE_URLS = {
    "datadoghq.com": "https://http-intake.logs.datadoghq.com",
    "datadoghq.eu": "https://http-intake.logs.datadoghq.eu",
    "us3.datadoghq.com": "https://http-intake.logs.us3.datadoghq.com",
    "us5.datadoghq.com": "https://http-intake.logs.us5.datadoghq.com",
    "ap1.datadoghq.com": "https://http-intake.logs.ap1.datadoghq.com",
}

DD_INTAKE_URL = DD_INTAKE_URLS.get(DD_SITE, DD_INTAKE_URLS["datadoghq.com"])

_LOGGING_CONFIGURED = False


def tracer_injection(_logger: Any, _log_method: str, event_dict: Dict) -> Dict:
    """
    Inject Datadog trace correlation into logs.
    Adds: dd.trace_id, dd.span_id, dd.service, dd.version, dd.env
    """
    if DDTRACE_AVAILABLE and tracer:
        try:
            trace_context = tracer.get_log_correlation_context()
            if trace_context:
                event_dict.update(trace_context)
        except Exception:
            pass
    return event_dict


class BatchingDatadogHandler(logging.Handler):
    """
    Async logging handler that batches logs and sends to Datadog HTTP API.
    """

    def __init__(
        self,
        api_key: str,
        intake_url: str,
        service: str,
        env: str,
        batch_size: int = 10,
        flush_interval: float = 1.0,
    ):
        super().__init__()
        self.api_key = api_key
        self.intake_url = f"{intake_url}/v1/input/{api_key}"
        self.service = service
        self.env = env
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self._batch: List[Dict] = []
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None
        self._error_count = 0
        self._last_flush = time.monotonic()
        self._flush_thread: threading.Thread | None = None
        self._stop_flush = threading.Event()

        self._start_flush_thread()

    def _start_flush_thread(self):
        def auto_flush():
            while not self._stop_flush.is_set():
                time.sleep(self.flush_interval)
                with self._lock:
                    if self._batch and (time.monotonic() - self._last_flush) >= self.flush_interval:
                        self._flush_batch()

        self._flush_thread = threading.Thread(target=auto_flush, daemon=True)
        self._flush_thread.start()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=5.0)
        return self._client

    def _parse_log_data(self, record: logging.LogRecord) -> Dict:
        formatted_message = self.format(record)
        try:
            return json.loads(formatted_message)
        except (json.JSONDecodeError, TypeError):
            try:
                import ast

                data = ast.literal_eval(formatted_message)
                if isinstance(data, dict):
                    return data
            except (ValueError, SyntaxError):
                pass
            return {"message": formatted_message}

    def _build_log_entry(self, record: logging.LogRecord) -> Dict:
        log_data = self._parse_log_data(record)

        main_message = log_data.pop("msg", log_data.pop("message", self.format(record)))
        log_level_value = log_data.pop("level", record.levelname.lower())
        log_data.pop("timestamp", None)

        log_entry = {
            "message": main_message,
            "level": log_level_value,
            "timestamp": int(record.created * 1000),
            "service": self.service,
            "ddsource": "python",
            "logger": {
                "name": record.name,
                "method_name": record.funcName,
                "thread_name": record.threadName,
            },
        }

        dd_fields = {k: log_data.pop(k) for k in list(log_data.keys()) if k.startswith("dd.")}
        log_entry.update(dd_fields)

        tags = [
            f"service:{self.service}",
            f"env:{self.env}",
            f"level:{log_level_value}",
        ]

        excluded = {"message", "level", "timestamp", "service", "env", "ddsource", "msg"}
        for key, value in log_data.items():
            if key not in excluded and value is not None:
                if isinstance(value, (dict, list)):
                    log_entry[key] = json.dumps(value)
                else:
                    log_entry[key] = str(value)
                    if len(str(value)) < 200:
                        tags.append(f"{key}:{str(value)}")

        log_entry["ddtags"] = ",".join(tags)
        return log_entry

    def _flush_batch(self):
        if not self._batch:
            return

        payload = self._batch[:]
        self._batch.clear()
        self._last_flush = time.monotonic()

        def send():
            try:
                client = self._get_client()
                response = client.post(
                    self.intake_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 200:
                    with self._lock:
                        if self._error_count > 0:
                            sys.stderr.write(
                                f"Datadog: recovered after {self._error_count} errors\n"
                            )
                            sys.stderr.flush()
                            self._error_count = 0
                else:
                    with self._lock:
                        self._error_count += 1
                        if self._error_count <= 3:
                            sys.stderr.write(
                                f"Datadog HTTP error {response.status_code}: {response.text}\n"
                            )
                            sys.stderr.flush()
            except Exception as e:
                with self._lock:
                    self._error_count += 1
                    if self._error_count <= 3:
                        sys.stderr.write(f"Datadog send error: {e}\n")
                        sys.stderr.flush()

        threading.Thread(target=send, daemon=True).start()

    def emit(self, record: logging.LogRecord):
        try:
            log_entry = self._build_log_entry(record)

            with self._lock:
                self._batch.append(log_entry)

                if len(self._batch) >= self.batch_size:
                    self._flush_batch()
        except Exception:
            pass

    def flush(self):
        with self._lock:
            self._flush_batch()

    def close(self):
        self._stop_flush.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=2.0)

        with self._lock:
            self._flush_batch()

        if self._client:
            self._client.close()

        super().close()


class HealthEndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "/health" not in message and '"/health' not in message


def configure_logging(
    *,
    service: str | None = None,
    env: str | None = None,
    api_key: str | None = None,
    site: str | None = None,
) -> structlog.stdlib.BoundLogger:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return structlog.get_logger()

    resolved_api_key = api_key or DD_API_KEY
    resolved_site = site or DD_SITE
    resolved_service = service or DD_SERVICE
    resolved_env = env or DD_ENV
    resolved_intake_url = DD_INTAKE_URLS.get(resolved_site, DD_INTAKE_URLS["datadoghq.com"])

    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if resolved_api_key and HTTPX_AVAILABLE:
        try:
            dd_handler = BatchingDatadogHandler(
                api_key=resolved_api_key,
                intake_url=resolved_intake_url,
                service=resolved_service,
                env=resolved_env,
                batch_size=10,
                flush_interval=1.0,
            )
            dd_handler.setLevel(log_level)
            handlers.append(dd_handler)

            atexit.register(dd_handler.close)

            sys.stderr.write(
                "Datadog: initialized (service="
                f"{resolved_service}, env={resolved_env}, batching=10 logs/request)\n"
            )
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"Datadog: init failed: {e}\n")
            sys.stderr.flush()
    elif not resolved_api_key:
        sys.stderr.write("Datadog: DD_API_KEY not set\n")
        sys.stderr.flush()
    elif not HTTPX_AVAILABLE:
        sys.stderr.write("Datadog: httpx not available\n")
        sys.stderr.flush()

    log_queue: Queue = Queue(maxsize=1000)
    queue_handler = QueueHandler(log_queue)
    queue_listener = QueueListener(log_queue, *handlers, respect_handler_level=True)
    queue_listener.start()

    atexit.register(queue_listener.stop)

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        handlers=[queue_handler],
    )

    health_filter = HealthEndpointFilter()

    for logger_name in [
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
    ]:
        try:
            third_party_logger = logging.getLogger(logger_name)
            if third_party_logger.level == logging.NOTSET:
                third_party_logger.setLevel(log_level)
            third_party_logger.propagate = True

            if logger_name == "uvicorn.access":
                third_party_logger.addFilter(health_filter)
        except Exception:
            pass

    try:
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.setLevel(logging.WARNING)
        httpx_logger.propagate = True
    except Exception:
        pass

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            tracer_injection,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.EventRenamer("msg"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    sys.stderr.write(
        f"Logging: initialized (level={LOG_LEVEL}, async=True, ddtrace={DDTRACE_AVAILABLE})\n"
    )
    sys.stderr.flush()

    _LOGGING_CONFIGURED = True
    return structlog.get_logger()


logger = configure_logging()
