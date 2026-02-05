"""
Manor Logger - Structured logging with Datadog integration.

BASIC USAGE:
    from manor.logger import logger
    logger.info("User logged in", user_id="123")

WITH REQUEST CONTEXT (FastAPI):
    from fastapi import FastAPI
    from manor.logger import logger, RequestContextMiddleware

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/users/{user_id}")
    async def get_user(user_id: str):
        # request_id is automatically included in all logs
        logger.info("Fetching user", user_id=user_id)
        return {"user_id": user_id}

PROPAGATING TO DOWNSTREAM SERVICES:
    from manor.logger import get_correlation_headers
    import httpx

    async def call_service_b():
        headers = get_correlation_headers()
        response = await httpx.get("http://service-b/api", headers=headers)
        return response.json()
"""

from .context import (
    RequestContextMiddleware,
    clear_context,
    generate_request_id,
    get_correlation_headers,
    get_extra_context,
    get_request_id,
    inject_request_context,
    set_extra_context,
    set_request_id,
    with_request_context,
)
from .direct_logger import DirectDatadogLogger, log_datadog
from .llm_instrumentation import (
    DEFAULT_INSTRUMENTATION,
    InstrumentationConfig,
    extract_token_usage,
    instrument_llm_call,
    trace_llm_pipeline,
)
from .structured_logger import configure_logging, logger

__all__ = [
    # Main logger
    "logger",
    "configure_logging",
    # Request context (for distributed tracing)
    "RequestContextMiddleware",
    "get_request_id",
    "set_request_id",
    "generate_request_id",
    "get_correlation_headers",
    "get_extra_context",
    "set_extra_context",
    "clear_context",
    "inject_request_context",
    "with_request_context",
    # Direct Datadog logging (for workers)
    "DirectDatadogLogger",
    "log_datadog",
    # LLM instrumentation
    "DEFAULT_INSTRUMENTATION",
    "InstrumentationConfig",
    "extract_token_usage",
    "instrument_llm_call",
    "trace_llm_pipeline",
]
