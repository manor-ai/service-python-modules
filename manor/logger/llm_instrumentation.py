"""
LLM instrumentation helpers for Datadog APM.
"""

from __future__ import annotations

import functools
import os
import time
from typing import Any, Callable

try:
    from ddtrace import tracer

    DDTRACE_AVAILABLE = True
except ImportError:
    tracer = None
    DDTRACE_AVAILABLE = False

from .direct_logger import log_datadog


class InstrumentationConfig:
    def __init__(self, enabled_types: set[str] | None = None) -> None:
        if enabled_types is None:
            raw = os.getenv("LLM_INSTRUMENTATION_TYPES", "llm,pipeline")
            enabled_types = {item.strip() for item in raw.split(",") if item.strip()}
        self.enabled_types = enabled_types

    def is_enabled(self, instrumentation_type: str) -> bool:
        return "*" in self.enabled_types or instrumentation_type in self.enabled_types


DEFAULT_INSTRUMENTATION = InstrumentationConfig()


def instrument_llm_call(
    operation_name: str = "llm.call",
    instrumentation_type: str = "llm",
    config: InstrumentationConfig | None = None,
):
    """
    Decorator to instrument LLM calls with Datadog APM tracing.
    """
    config = config or DEFAULT_INSTRUMENTATION

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not config.is_enabled(instrumentation_type):
                return await func(*args, **kwargs)

            start_time = time.monotonic()
            llm_service = os.getenv("LLM_DD_SERVICE", os.getenv("DD_SERVICE", "llm"))
            if DDTRACE_AVAILABLE and tracer:
                with tracer.trace(operation_name, service=llm_service) as span:
                    span.set_tag("span.kind", "llm")
                    span.set_tag("llm.operation", operation_name)

                    model = kwargs.get("model") or getattr(kwargs.get("lm"), "model", "unknown")
                    span.set_tag("llm.model", model)

                    try:
                        result = await func(*args, **kwargs)
                        token_usage = extract_token_usage(result)
                        if token_usage:
                            span.set_tag("llm.prompt_tokens", token_usage.get("prompt_tokens", 0))
                            span.set_tag(
                                "llm.completion_tokens", token_usage.get("completion_tokens", 0)
                            )
                            span.set_tag("llm.total_tokens", token_usage.get("total_tokens", 0))

                        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                        span.set_tag("llm.duration_ms", duration_ms)

                        log_datadog(
                            "llm_call",
                            operation=operation_name,
                            model=model,
                            duration_ms=duration_ms,
                            **token_usage if token_usage else {},
                        )

                        return result
                    except Exception as e:
                        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                        span.set_tag("error", True)
                        span.set_tag("error.type", type(e).__name__)
                        span.set_tag("error.message", str(e))
                        span.set_tag("llm.duration_ms", duration_ms)

                        log_datadog(
                            "llm_call_failed",
                            level="error",
                            operation=operation_name,
                            duration_ms=duration_ms,
                            error_type=type(e).__name__,
                            error_message=str(e),
                        )
                        raise

            result = await func(*args, **kwargs)
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            log_datadog(
                "llm_call",
                operation=operation_name,
                duration_ms=duration_ms,
            )
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not config.is_enabled(instrumentation_type):
                return func(*args, **kwargs)

            start_time = time.monotonic()
            llm_service = os.getenv("LLM_DD_SERVICE", os.getenv("DD_SERVICE", "llm"))
            if DDTRACE_AVAILABLE and tracer:
                with tracer.trace(operation_name, service=llm_service) as span:
                    span.set_tag("span.kind", "llm")
                    span.set_tag("llm.operation", operation_name)

                    model = kwargs.get("model") or getattr(kwargs.get("lm"), "model", "unknown")
                    span.set_tag("llm.model", model)

                    try:
                        result = func(*args, **kwargs)
                        token_usage = extract_token_usage(result)
                        if token_usage:
                            span.set_tag("llm.prompt_tokens", token_usage.get("prompt_tokens", 0))
                            span.set_tag(
                                "llm.completion_tokens", token_usage.get("completion_tokens", 0)
                            )
                            span.set_tag("llm.total_tokens", token_usage.get("total_tokens", 0))

                        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                        span.set_tag("llm.duration_ms", duration_ms)

                        log_datadog(
                            "llm_call",
                            operation=operation_name,
                            model=model,
                            duration_ms=duration_ms,
                            **token_usage if token_usage else {},
                        )
                        return result
                    except Exception as e:
                        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                        span.set_tag("error", True)
                        span.set_tag("error.type", type(e).__name__)
                        span.set_tag("error.message", str(e))

                        log_datadog(
                            "llm_call_failed",
                            level="error",
                            operation=operation_name,
                            duration_ms=duration_ms,
                            error_type=type(e).__name__,
                        )
                        raise

            result = func(*args, **kwargs)
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            log_datadog(
                "llm_call",
                operation=operation_name,
                duration_ms=duration_ms,
            )
            return result

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def extract_token_usage(result: Any) -> dict | None:
    if not result:
        return None

    token_usage: dict[str, Any] = {}

    if hasattr(result, "usage") and result.usage:
        usage = result.usage
        token_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
    elif isinstance(result, dict) and "usage" in result:
        usage = result["usage"]
        token_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    elif hasattr(result, "_hidden_params") and hasattr(result._hidden_params, "response_cost"):
        token_usage["cost"] = result._hidden_params.response_cost

    return token_usage if token_usage else None


def trace_llm_pipeline(
    pipeline_name: str,
    instrumentation_type: str = "pipeline",
    config: InstrumentationConfig | None = None,
):
    """
    Decorator to trace entire LLM pipelines.
    """
    config = config or DEFAULT_INSTRUMENTATION

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not config.is_enabled(instrumentation_type):
                return await func(*args, **kwargs)

            start_time = time.monotonic()

            llm_service = os.getenv("LLM_DD_SERVICE", os.getenv("DD_SERVICE", "llm"))
            if DDTRACE_AVAILABLE and tracer:
                with tracer.trace(f"llm.pipeline.{pipeline_name}", service=llm_service) as span:
                    span.set_tag("span.kind", "pipeline")
                    span.set_tag("pipeline.name", pipeline_name)

                    try:
                        result = await func(*args, **kwargs)

                        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                        span.set_tag("pipeline.duration_ms", duration_ms)
                        span.set_tag("pipeline.success", True)

                        log_datadog(
                            "llm_pipeline_completed",
                            pipeline=pipeline_name,
                            duration_ms=duration_ms,
                        )

                        return result
                    except Exception as e:
                        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                        span.set_tag("error", True)
                        span.set_tag("error.type", type(e).__name__)
                        span.set_tag("error.message", str(e))
                        span.set_tag("pipeline.duration_ms", duration_ms)
                        span.set_tag("pipeline.success", False)

                        log_datadog(
                            "llm_pipeline_failed",
                            level="error",
                            pipeline=pipeline_name,
                            duration_ms=duration_ms,
                            error_type=type(e).__name__,
                        )
                        raise

            result = await func(*args, **kwargs)
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            log_datadog(
                "llm_pipeline_completed",
                pipeline=pipeline_name,
                duration_ms=duration_ms,
            )
            return result

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not config.is_enabled(instrumentation_type):
                return func(*args, **kwargs)

            start_time = time.monotonic()

            llm_service = os.getenv("LLM_DD_SERVICE", os.getenv("DD_SERVICE", "llm"))
            if DDTRACE_AVAILABLE and tracer:
                with tracer.trace(f"llm.pipeline.{pipeline_name}", service=llm_service) as span:
                    span.set_tag("span.kind", "pipeline")
                    span.set_tag("pipeline.name", pipeline_name)

                    try:
                        result = func(*args, **kwargs)

                        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                        span.set_tag("pipeline.duration_ms", duration_ms)
                        span.set_tag("pipeline.success", True)

                        log_datadog(
                            "llm_pipeline_completed",
                            pipeline=pipeline_name,
                            duration_ms=duration_ms,
                        )

                        return result
                    except Exception as e:
                        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                        span.set_tag("error", True)
                        span.set_tag("error.type", type(e).__name__)
                        span.set_tag("error.message", str(e))

                        log_datadog(
                            "llm_pipeline_failed",
                            level="error",
                            pipeline=pipeline_name,
                            duration_ms=duration_ms,
                            error_type=type(e).__name__,
                        )
                        raise

            result = func(*args, **kwargs)
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            log_datadog(
                "llm_pipeline_completed",
                pipeline=pipeline_name,
                duration_ms=duration_ms,
            )
            return result

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
