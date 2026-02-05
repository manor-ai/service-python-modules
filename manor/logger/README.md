# Manor Logger

Structured logging with Datadog integration and distributed tracing support.

## Features

- **Structured JSON logging** via structlog
- **Datadog integration** with automatic log shipping via HTTP API
- **Distributed tracing** with request ID propagation across services
- **Datadog APM correlation** with automatic trace/span ID injection
- **Fork-safe** for Gunicorn with multiple workers
- **Non-blocking** with async log processing via queue

## Installation

```bash
pip install manor
```

## Quick Start

```python
from manor.logger import logger

logger.info("User logged in", user_id="123", action="login")
logger.error("Payment failed", order_id="456", error="insufficient_funds")
```

Output (JSON):
```json
{
  "msg": "User logged in",
  "level": "info",
  "timestamp": "2024-01-15T10:30:00.000000Z",
  "user_id": "123",
  "action": "login"
}
```

## Configuration

All configuration is done via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `DD_API_KEY` | Datadog API key (enables Datadog logging) | (none) |
| `DD_SITE` | Datadog site/region | `us5.datadoghq.com` |
| `DD_SERVICE` | Service name for Datadog | `app` |
| `DD_ENV` | Environment tag | `dev` |

## Usage with FastAPI

### Basic Setup

```python
from fastapi import FastAPI
from manor.logger import logger

app = FastAPI()

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    logger.info("Fetching user", user_id=user_id)
    return {"user_id": user_id}
```

### With Request Context (Distributed Tracing)

Add the middleware to automatically extract and propagate `X-Request-ID`:

```python
from fastapi import FastAPI
from manor.logger import logger, RequestContextMiddleware

app = FastAPI()

# Add middleware - extracts X-Request-ID from incoming requests
app.add_middleware(RequestContextMiddleware)

@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    # request_id is automatically included in all logs
    logger.info("Fetching order", order_id=order_id)
    
    # Call downstream service with correlation headers
    order = await fetch_order_details(order_id)
    
    logger.info("Order fetched", order_id=order_id, status=order["status"])
    return order
```

### Propagating to Downstream Services

When calling other services, use `get_correlation_headers()` to propagate the request ID:

```python
import httpx
from manor.logger import logger, get_correlation_headers

async def fetch_order_details(order_id: str) -> dict:
    # Get headers with X-Request-ID, X-Correlation-ID, traceparent
    headers = get_correlation_headers()
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://order-service/orders/{order_id}",
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
```

Headers propagated:
- `X-Request-ID`: The correlation ID
- `X-Correlation-ID`: Alias for compatibility
- `x-datadog-trace-id`: Datadog trace ID (if ddtrace is installed)
- `x-datadog-parent-id`: Datadog span ID (if ddtrace is installed)
- `traceparent`: W3C Trace Context (if ddtrace is installed)

### Adding Extra Context

Add user or tenant information to all logs in a request:

```python
from fastapi import FastAPI, Request
from manor.logger import logger, RequestContextMiddleware, set_extra_context

app = FastAPI()
app.add_middleware(RequestContextMiddleware)

@app.middleware("http")
async def add_user_context(request: Request, call_next):
    # After authentication, add user info to context
    user = await get_current_user(request)
    if user:
        set_extra_context(
            user_id=user.id,
            tenant_id=user.tenant_id,
            user_email=user.email,
        )
    
    return await call_next(request)

@app.get("/dashboard")
async def get_dashboard():
    # All logs automatically include user_id, tenant_id, user_email
    logger.info("Loading dashboard")
    return {"status": "ok"}
```

## Usage in Background Tasks / Workers

For Celery tasks or background jobs, use `with_request_context()`:

```python
from celery import Celery
from manor.logger import logger, with_request_context

celery_app = Celery("tasks")

@celery_app.task
def process_order(order_id: str, request_id: str):
    # Maintain the same request_id from the original HTTP request
    with with_request_context(request_id):
        logger.info("Processing order", order_id=order_id)
        
        # Do work...
        
        logger.info("Order processed", order_id=order_id)
```

When enqueuing the task, pass the request ID:

```python
from manor.logger import get_request_id

@app.post("/orders")
async def create_order(order: OrderCreate):
    order_id = await save_order(order)
    
    # Pass request_id to background task
    process_order.delay(order_id, request_id=get_request_id())
    
    return {"order_id": order_id}
```

## Request Flow Example

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           REQUEST FLOW                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Client                                                                  │
│    │                                                                     │
│    │ GET /api/orders/123                                                │
│    │ X-Request-ID: req-abc-123  (or generated if not present)          │
│    ▼                                                                     │
│  ┌──────────────────┐                                                   │
│  │  Service A       │                                                   │
│  │  (API Gateway)   │                                                   │
│  │                  │  Log: {"msg":"...", "request_id":"req-abc-123"}  │
│  └────────┬─────────┘                                                   │
│           │                                                              │
│           │ GET /internal/inventory                                     │
│           │ X-Request-ID: req-abc-123                                   │
│           │ X-Correlation-ID: req-abc-123                               │
│           │ traceparent: 00-xxxxx-yyyyy-01                              │
│           ▼                                                              │
│  ┌──────────────────┐                                                   │
│  │  Service B       │                                                   │
│  │  (Inventory)     │                                                   │
│  │                  │  Log: {"msg":"...", "request_id":"req-abc-123"}  │
│  └────────┬─────────┘                                                   │
│           │                                                              │
│           │ GET /internal/pricing                                       │
│           │ X-Request-ID: req-abc-123                                   │
│           ▼                                                              │
│  ┌──────────────────┐                                                   │
│  │  Service C       │                                                   │
│  │  (Pricing)       │                                                   │
│  │                  │  Log: {"msg":"...", "request_id":"req-abc-123"}  │
│  └──────────────────┘                                                   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Searching in Datadog

With request ID propagation, you can search across all services:

```
# All logs for a specific request
@request_id:"req-abc-123"

# Logs from a specific service for a request
@request_id:"req-abc-123" service:api-gateway

# All errors for a request
@request_id:"req-abc-123" level:error

# All logs for a user
@user_id:"user-456"
```

## Direct Datadog Logging (for Workers)

For Celery workers or scripts without structlog, use `log_datadog()`:

```python
from manor.logger import log_datadog

def celery_task():
    log_datadog(
        "Task started",
        level="info",
        task_id="abc-123",
        queue="high-priority",
    )
    
    try:
        # Do work...
        log_datadog("Task completed", level="info", task_id="abc-123")
    except Exception as e:
        log_datadog(
            f"Task failed: {e}",
            level="error",
            task_id="abc-123",
            error=str(e),
        )
        raise
```

## LLM Instrumentation

For AI/LLM applications, use the instrumentation helpers:

```python
from manor.logger import instrument_llm_call, trace_llm_pipeline

# Instrument a single LLM call
@instrument_llm_call(model="gpt-4", operation="chat")
async def chat_with_gpt(messages: list[dict]) -> str:
    response = await openai.chat.completions.create(
        model="gpt-4",
        messages=messages,
    )
    return response.choices[0].message.content

# Trace an entire pipeline
@trace_llm_pipeline(name="rag-pipeline")
async def rag_pipeline(query: str) -> str:
    # Retrieval
    docs = await retrieve_documents(query)
    
    # Generation
    response = await chat_with_gpt([
        {"role": "system", "content": "Answer based on the documents."},
        {"role": "user", "content": f"Documents: {docs}\n\nQuery: {query}"},
    ])
    
    return response
```

## API Reference

### Main Logger

| Function | Description |
|----------|-------------|
| `logger` | Pre-configured structlog logger instance |
| `configure_logging(service, env, api_key, site)` | Manually configure logging |

### Request Context

| Function | Description |
|----------|-------------|
| `RequestContextMiddleware` | FastAPI middleware for request ID extraction |
| `get_request_id()` | Get current request ID |
| `set_request_id(id)` | Set request ID (used by middleware) |
| `get_correlation_headers()` | Get headers for downstream calls |
| `set_extra_context(**kwargs)` | Add extra fields to all logs |
| `get_extra_context()` | Get current extra context |
| `clear_context()` | Clear all context (used by middleware) |
| `with_request_context(id)` | Context manager for background tasks |

### Direct Logging

| Function | Description |
|----------|-------------|
| `log_datadog(message, level, **kwargs)` | Send log directly to Datadog |
| `DirectDatadogLogger` | Class for direct Datadog logging |

### LLM Instrumentation

| Function | Description |
|----------|-------------|
| `instrument_llm_call(model, operation)` | Decorator for LLM calls |
| `trace_llm_pipeline(name)` | Decorator for LLM pipelines |
| `extract_token_usage(response)` | Extract token counts from response |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         LOG FLOW                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  logger.info("Hello", user_id="123")                                │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    STRUCTLOG PROCESSORS                      │    │
│  │  1. add_log_level      → {"level": "info"}                  │    │
│  │  2. TimeStamper        → {"timestamp": "2024-01-15T..."}    │    │
│  │  3. inject_request_context → {"request_id": "req-abc"}      │    │
│  │  4. add_datadog_trace  → {"dd.trace_id": "123456"}          │    │
│  │  5. JSONRenderer       → '{"msg":"Hello",...}'              │    │
│  └─────────────────────────────────────────────────────────────┘    │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    ASYNC QUEUE                               │    │
│  │  QueueHandler → Queue(maxsize=1000) → QueueListener         │    │
│  │  (non-blocking)                       (background thread)    │    │
│  └─────────────────────────────────────────────────────────────┘    │
│         │                                                            │
│         ├──────────────────────┬────────────────────────────────    │
│         ▼                      ▼                                     │
│  ┌─────────────┐      ┌─────────────────────────────────────┐       │
│  │   STDOUT    │      │         DATADOG HTTP HANDLER         │       │
│  │  (console)  │      │  - Batches logs (10 per request)    │       │
│  └─────────────┘      │  - Auto-flush every 1 second        │       │
│                       │  - Sends in background threads       │       │
│                       │  - Fork-safe (detects PID change)    │       │
│                       └─────────────────────────────────────┘       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Gunicorn / Uvicorn Compatibility

The logger is designed to work correctly with:

- **Uvicorn**: `uvicorn app:app`
- **Gunicorn + Uvicorn**: `gunicorn app:app -k uvicorn.workers.UvicornWorker`
- **Gunicorn with preload**: `gunicorn app:app --preload -k uvicorn.workers.UvicornWorker`

Fork safety is ensured by:
1. **Lazy initialization**: Logger is configured on first use, not at import
2. **PID detection**: HTTP client is recreated after fork
3. **contextvars**: Request context is isolated per-request in async code
