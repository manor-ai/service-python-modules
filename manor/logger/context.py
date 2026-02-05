"""
Request context propagation for distributed tracing.

PROBLEM:
    When a request flows through multiple services, we need to track it
    end-to-end. Datadog's dd-trace helps, but sometimes traces are lost
    or disconnected. A simple request ID that propagates through all
    services provides a reliable fallback.

SOLUTION:
    1. Extract X-Request-ID from incoming request headers
    2. Store it in contextvars (async-safe, per-request storage)
    3. Automatically inject it into all logs
    4. Propagate it to downstream HTTP calls

USAGE WITH FASTAPI:
    from fastapi import FastAPI, Request
    from manor.logger import logger
    from manor.logger.context import RequestContextMiddleware, get_request_id

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/users/{user_id}")
    async def get_user(user_id: str):
        # request_id is automatically included in all logs
        logger.info("Fetching user", user_id=user_id)
        return {"user_id": user_id}

USAGE WITH HTTPX (propagating to downstream services):
    from manor.logger.context import get_correlation_headers
    import httpx

    async def call_downstream():
        headers = get_correlation_headers()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://service-b/api/data",
                headers=headers,
            )
        return response.json()

HEADERS USED:
    - X-Request-ID: Primary correlation ID (generated if not present)
    - X-Correlation-ID: Alias for X-Request-ID (some systems use this)
    - traceparent: W3C Trace Context (if available from dd-trace)
"""

from __future__ import annotations

import contextvars
import uuid
from typing import Any, Callable

# =============================================================================
# CONTEXT VARIABLES
# =============================================================================
# contextvars are like thread-locals but work correctly with async code.
# Each request gets its own isolated context.

# The request ID for the current request
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id",
    default=None,
)

# Additional context fields (user_id, tenant_id, etc.)
_extra_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "extra_context",
    default={},
)


# =============================================================================
# CONTEXT GETTERS AND SETTERS
# =============================================================================


def get_request_id() -> str | None:
    """
    Get the current request ID.
    
    Returns:
        The request ID if set, None otherwise.
    
    Example:
        request_id = get_request_id()
        if request_id:
            print(f"Processing request {request_id}")
    """
    return _request_id.get()


def set_request_id(request_id: str) -> None:
    """
    Set the request ID for the current context.
    
    This is typically called by middleware at the start of a request.
    
    Args:
        request_id: The request ID to set
    
    Example:
        set_request_id("abc-123-def-456")
    """
    _request_id.set(request_id)


def generate_request_id() -> str:
    """
    Generate a new unique request ID.
    
    Uses UUID4 for guaranteed uniqueness across all services.
    
    Returns:
        A new UUID string like "550e8400-e29b-41d4-a716-446655440000"
    """
    return str(uuid.uuid4())


def get_extra_context() -> dict[str, Any]:
    """
    Get all extra context fields.
    
    Returns:
        Dictionary of extra context fields
    """
    return _extra_context.get().copy()


def set_extra_context(**kwargs: Any) -> None:
    """
    Set extra context fields for the current request.
    
    These fields will be included in all logs for this request.
    
    Args:
        **kwargs: Key-value pairs to add to context
    
    Example:
        set_extra_context(user_id="user-123", tenant_id="tenant-456")
    """
    current = _extra_context.get().copy()
    current.update(kwargs)
    _extra_context.set(current)


def clear_context() -> None:
    """
    Clear all context for the current request.
    
    Called by middleware at the end of a request.
    """
    _request_id.set(None)
    _extra_context.set({})


# =============================================================================
# CORRELATION HEADERS
# =============================================================================


def get_correlation_headers() -> dict[str, str]:
    """
    Get headers to propagate to downstream services.
    
    Use this when making HTTP calls to other services to maintain
    the correlation chain.
    
    Returns:
        Dictionary of headers to include in downstream requests
    
    Example:
        import httpx
        
        async def call_service_b():
            headers = get_correlation_headers()
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://service-b/api/data",
                    headers=headers,
                )
            return response.json()
    """
    headers: dict[str, str] = {}
    
    # Add request ID
    request_id = get_request_id()
    if request_id:
        headers["X-Request-ID"] = request_id
        headers["X-Correlation-ID"] = request_id  # Alias for compatibility
    
    # Add Datadog trace context if available
    try:
        from ddtrace import tracer
        span = tracer.current_span()
        if span:
            # Add Datadog-specific headers
            headers["x-datadog-trace-id"] = str(span.trace_id)
            headers["x-datadog-parent-id"] = str(span.span_id)
            
            # Add W3C traceparent for interoperability
            # Format: version-trace_id-parent_id-flags
            trace_id_hex = format(span.trace_id, "032x")
            span_id_hex = format(span.span_id, "016x")
            headers["traceparent"] = f"00-{trace_id_hex}-{span_id_hex}-01"
    except ImportError:
        pass
    except Exception:
        pass
    
    return headers


# =============================================================================
# STRUCTLOG PROCESSOR
# =============================================================================


def inject_request_context(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Structlog processor that injects request context into logs.
    
    This processor adds:
        - request_id: The correlation ID for the request
        - Any extra context set via set_extra_context()
    
    IMPORTANT: Add this processor to your structlog configuration.
    
    Args:
        logger: The structlog logger (unused)
        method_name: The log method name (unused)
        event_dict: The log event dictionary to enrich
    
    Returns:
        The enriched event dictionary
    
    Example structlog configuration:
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                inject_request_context,  # <-- Add this
                structlog.processors.JSONRenderer(),
            ],
        )
    """
    # Add request ID if present
    request_id = get_request_id()
    if request_id:
        event_dict["request_id"] = request_id
    
    # Add extra context fields
    extra = get_extra_context()
    for key, value in extra.items():
        # Don't overwrite existing fields
        if key not in event_dict:
            event_dict[key] = value
    
    return event_dict


# =============================================================================
# FASTAPI MIDDLEWARE
# =============================================================================


class RequestContextMiddleware:
    """
    FastAPI/Starlette middleware for request context propagation.
    
    WHAT IT DOES:
        1. Extracts X-Request-ID from incoming request (or generates one)
        2. Stores it in contextvars for the duration of the request
        3. Adds X-Request-ID to the response headers
        4. Clears context after the request completes
    
    USAGE:
        from fastapi import FastAPI
        from manor.logger.context import RequestContextMiddleware

        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)
    
    REQUEST FLOW:
        1. Request arrives with X-Request-ID: "abc-123"
        2. Middleware extracts "abc-123" and stores in context
        3. All logs during request include request_id="abc-123"
        4. Response includes X-Request-ID: "abc-123"
        5. Context is cleared for next request
    
    HEADER PRIORITY:
        1. X-Request-ID (preferred)
        2. X-Correlation-ID (fallback)
        3. Generate new UUID (if neither present)
    """

    def __init__(self, app: Any):
        """
        Initialize the middleware.
        
        Args:
            app: The ASGI application
        """
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable,
        send: Callable,
    ) -> None:
        """
        Process a request.
        
        Args:
            scope: ASGI scope dictionary
            receive: ASGI receive callable
            send: ASGI send callable
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Extract request ID from headers
        request_id = self._extract_request_id(scope)
        
        # Set context for this request
        set_request_id(request_id)
        
        # Wrapper to inject request ID into response headers
        async def send_with_request_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                # Add request ID to response headers
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)
        
        try:
            # Process the request
            await self.app(scope, receive, send_with_request_id)
        finally:
            # Always clear context after request
            clear_context()

    def _extract_request_id(self, scope: dict[str, Any]) -> str:
        """
        Extract request ID from headers or generate a new one.
        
        Args:
            scope: ASGI scope dictionary
        
        Returns:
            The request ID (extracted or generated)
        """
        headers = dict(scope.get("headers", []))
        
        # Try X-Request-ID first
        request_id = headers.get(b"x-request-id")
        if request_id:
            return request_id.decode()
        
        # Try X-Correlation-ID as fallback
        correlation_id = headers.get(b"x-correlation-id")
        if correlation_id:
            return correlation_id.decode()
        
        # Generate new ID if not present
        return generate_request_id()


# =============================================================================
# CONVENIENCE FUNCTION FOR MANUAL CONTEXT
# =============================================================================


def with_request_context(request_id: str | None = None):
    """
    Context manager for manual request context setup.
    
    Use this in workers, background tasks, or tests where you don't
    have the middleware.
    
    Args:
        request_id: The request ID to use (generated if None)
    
    Example:
        from manor.logger.context import with_request_context
        from manor.logger import logger

        async def background_task(task_id: str, request_id: str):
            with with_request_context(request_id):
                logger.info("Processing task", task_id=task_id)
                # All logs here include request_id
    """
    class RequestContextManager:
        def __init__(self, rid: str | None):
            self.request_id = rid or generate_request_id()
        
        def __enter__(self):
            set_request_id(self.request_id)
            return self.request_id
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            clear_context()
            return False
        
        async def __aenter__(self):
            set_request_id(self.request_id)
            return self.request_id
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            clear_context()
            return False
    
    return RequestContextManager(request_id)
