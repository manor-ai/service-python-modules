"""
Direct Datadog logger for worker contexts (Celery).
"""

from __future__ import annotations

import os
import time

import httpx

try:
    from ddtrace import tracer

    DDTRACE_AVAILABLE = True
except ImportError:
    tracer = None
    DDTRACE_AVAILABLE = False

DD_API_KEY = os.getenv("DD_API_KEY", "24b9e19b6d5bca4210cd6b077730e2e4")
DD_SITE = os.getenv("DD_SITE", "us5.datadoghq.com")
DD_INTAKE_URL = f"https://http-intake.logs.{DD_SITE}/v1/input/{DD_API_KEY}"

DEFAULT_SERVICE = os.getenv("DD_SERVICE", "manor-service-task")
DEFAULT_ENV = os.getenv("DD_ENV", os.getenv("ENVIRONMENT", "preprod"))


class DirectDatadogLogger:
    def __init__(
        self,
        service: str | None = None,
        env: str | None = None,
        intake_url: str | None = None,
    ) -> None:
        self.service = service or DEFAULT_SERVICE
        self.env = env or DEFAULT_ENV
        self.intake_url = intake_url or DD_INTAKE_URL
        self.client = httpx.Client(timeout=5.0)

    def log(self, message: str, level: str = "info", **extra_fields):
        try:
            tags = f"service:{self.service},env:{self.env},level:{level}"
            if extra_fields:
                tags += "," + ",".join(f"{k}:{v}" for k, v in extra_fields.items())

            log_entry = {
                "message": message,
                "level": level,
                "timestamp": int(time.time() * 1000),
                "service": self.service,
                "ddsource": "python",
                "ddtags": tags,
            }

            if DDTRACE_AVAILABLE and tracer:
                try:
                    trace_context = tracer.get_log_correlation_context()
                    if trace_context:
                        log_entry.update(trace_context)
                except Exception:
                    pass

            log_entry.update(extra_fields)

            self.client.post(
                self.intake_url,
                json=[log_entry],
                headers={"Content-Type": "application/json"},
            )

            print(f"[DD] {message}")
        except Exception as e:
            print(f"[DD ERROR] {message} ({e})")


_default_logger = DirectDatadogLogger()


def log_datadog(message: str, level: str = "info", **extra_fields):
    _default_logger.log(message, level=level, **extra_fields)
