"""
Tests for manor.logger module.

Run with:
    pytest tests/test_logger.py -v

Run with real Datadog integration:
    DD_API_KEY=your_api_key pytest tests/test_logger.py -v
"""

import asyncio
import json
import logging
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import structlog


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_logger_state():
    """Reset logger singleton state before each test."""
    # Import here to avoid side effects
    import manor.logger.structured_logger as sl
    
    # Save original state
    original_configured = sl._is_configured
    original_instance = sl._logger_instance
    
    # Reset state
    sl._is_configured = False
    sl._logger_instance = None
    
    # Also reset structlog
    structlog.reset_defaults()
    
    yield
    
    # Restore original state (optional, for cleanup)
    sl._is_configured = original_configured
    sl._logger_instance = original_instance


@pytest.fixture
def datadog_api_key():
    """Get Datadog API key from environment."""
    return os.getenv("DD_API_KEY", "")


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.Client for testing without real HTTP calls."""
    with patch("httpx.Client") as mock:
        mock_instance = MagicMock()
        mock_instance.post.return_value = MagicMock(status_code=200)
        mock.return_value = mock_instance
        yield mock_instance


# =============================================================================
# TESTS: BASIC LOGGING
# =============================================================================


class TestBasicLogging:
    """Test basic logging functionality."""

    def test_logger_import(self):
        """Test that logger can be imported."""
        from manor.logger import logger
        
        assert logger is not None

    def test_logger_is_lazy_proxy(self):
        """Test that logger is a lazy proxy, not configured at import."""
        from manor.logger import logger
        from manor.logger.structured_logger import LazyLoggerProxy
        
        assert isinstance(logger, LazyLoggerProxy)

    def test_configure_logging_returns_logger(self):
        """Test that configure_logging returns a structlog logger."""
        from manor.logger import configure_logging
        
        logger = configure_logging(service="test-service", env="cicd")
        
        assert logger is not None
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "debug")

    def test_configure_logging_is_singleton(self):
        """Test that configure_logging returns the same instance."""
        from manor.logger import configure_logging
        
        logger1 = configure_logging(service="test-1")
        logger2 = configure_logging(service="test-2")  # Different params
        
        # Should return same instance (singleton)
        assert logger1 is logger2

    def test_logger_info(self, capsys):
        """Test logger.info outputs to stdout."""
        from manor.logger import configure_logging
        
        logger = configure_logging(service="test-service", env="cicd")
        logger.info("Test message", user_id="123")
        
        # Give async queue time to process
        time.sleep(0.1)
        
        # Check stderr for initialization messages
        captured = capsys.readouterr()
        assert "Logger: READY" in captured.err

    def test_logger_with_extra_fields(self, capsys):
        """Test logger with extra fields."""
        from manor.logger import configure_logging
        
        logger = configure_logging(service="test-service", env="cicd")
        
        # Log with various field types
        logger.info(
            "User action",
            user_id="user-123",
            action="login",
            ip_address="192.168.1.1",
            metadata={"browser": "chrome", "version": "120"},
        )
        
        time.sleep(0.1)
        
        # Should not raise any errors
        captured = capsys.readouterr()
        assert "Logger: READY" in captured.err


# =============================================================================
# TESTS: REQUEST CONTEXT
# =============================================================================


class TestRequestContext:
    """Test request context functionality."""

    def test_get_request_id_default_none(self):
        """Test get_request_id returns None by default."""
        from manor.logger.context import get_request_id
        
        assert get_request_id() is None

    def test_set_and_get_request_id(self):
        """Test setting and getting request ID."""
        from manor.logger.context import get_request_id, set_request_id, clear_context
        
        try:
            set_request_id("test-request-123")
            assert get_request_id() == "test-request-123"
        finally:
            clear_context()

    def test_generate_request_id(self):
        """Test request ID generation."""
        from manor.logger.context import generate_request_id
        
        id1 = generate_request_id()
        id2 = generate_request_id()
        
        # Should be UUIDs
        assert len(id1) == 36  # UUID format: 8-4-4-4-12
        assert "-" in id1
        
        # Should be unique
        assert id1 != id2

    def test_extra_context(self):
        """Test extra context functionality."""
        from manor.logger.context import (
            set_extra_context,
            get_extra_context,
            clear_context,
        )
        
        try:
            set_extra_context(user_id="user-123", tenant_id="tenant-456")
            
            context = get_extra_context()
            assert context["user_id"] == "user-123"
            assert context["tenant_id"] == "tenant-456"
        finally:
            clear_context()

    def test_clear_context(self):
        """Test clearing context."""
        from manor.logger.context import (
            set_request_id,
            set_extra_context,
            get_request_id,
            get_extra_context,
            clear_context,
        )
        
        set_request_id("test-123")
        set_extra_context(user_id="user-123")
        
        clear_context()
        
        assert get_request_id() is None
        assert get_extra_context() == {}

    def test_with_request_context_sync(self):
        """Test with_request_context as sync context manager."""
        from manor.logger.context import with_request_context, get_request_id
        
        with with_request_context("my-request-id") as rid:
            assert rid == "my-request-id"
            assert get_request_id() == "my-request-id"
        
        # Should be cleared after exiting
        assert get_request_id() is None

    @pytest.mark.asyncio
    async def test_with_request_context_async(self):
        """Test with_request_context as async context manager."""
        from manor.logger.context import with_request_context, get_request_id
        
        async with with_request_context("async-request-id") as rid:
            assert rid == "async-request-id"
            assert get_request_id() == "async-request-id"
        
        # Should be cleared after exiting
        assert get_request_id() is None

    def test_with_request_context_generates_id(self):
        """Test with_request_context generates ID if not provided."""
        from manor.logger.context import with_request_context, get_request_id
        
        with with_request_context() as rid:
            assert rid is not None
            assert len(rid) == 36  # UUID format
            assert get_request_id() == rid


# =============================================================================
# TESTS: CORRELATION HEADERS
# =============================================================================


class TestCorrelationHeaders:
    """Test correlation header generation."""

    def test_get_correlation_headers_with_request_id(self):
        """Test correlation headers include request ID."""
        from manor.logger.context import (
            get_correlation_headers,
            set_request_id,
            clear_context,
        )
        
        try:
            set_request_id("test-correlation-123")
            
            headers = get_correlation_headers()
            
            assert headers["X-Request-ID"] == "test-correlation-123"
            assert headers["X-Correlation-ID"] == "test-correlation-123"
        finally:
            clear_context()

    def test_get_correlation_headers_empty_without_context(self):
        """Test correlation headers are empty without context."""
        from manor.logger.context import get_correlation_headers, clear_context
        
        clear_context()
        
        headers = get_correlation_headers()
        
        # Should not have request ID headers
        assert "X-Request-ID" not in headers


# =============================================================================
# TESTS: STRUCTLOG PROCESSOR
# =============================================================================


class TestStructlogProcessor:
    """Test structlog processor for request context injection."""

    def test_inject_request_context_adds_request_id(self):
        """Test processor adds request_id to event dict."""
        from manor.logger.context import (
            inject_request_context,
            set_request_id,
            clear_context,
        )
        
        try:
            set_request_id("processor-test-123")
            
            event_dict = {"msg": "test message"}
            result = inject_request_context(None, "info", event_dict)
            
            assert result["request_id"] == "processor-test-123"
            assert result["msg"] == "test message"
        finally:
            clear_context()

    def test_inject_request_context_adds_extra_context(self):
        """Test processor adds extra context fields."""
        from manor.logger.context import (
            inject_request_context,
            set_extra_context,
            clear_context,
        )
        
        try:
            set_extra_context(user_id="user-456", tenant_id="tenant-789")
            
            event_dict = {"msg": "test message"}
            result = inject_request_context(None, "info", event_dict)
            
            assert result["user_id"] == "user-456"
            assert result["tenant_id"] == "tenant-789"
        finally:
            clear_context()

    def test_inject_request_context_does_not_overwrite(self):
        """Test processor does not overwrite existing fields."""
        from manor.logger.context import (
            inject_request_context,
            set_extra_context,
            clear_context,
        )
        
        try:
            set_extra_context(user_id="context-user")
            
            # Event dict already has user_id
            event_dict = {"msg": "test", "user_id": "explicit-user"}
            result = inject_request_context(None, "info", event_dict)
            
            # Should keep the explicit value
            assert result["user_id"] == "explicit-user"
        finally:
            clear_context()


# =============================================================================
# TESTS: FASTAPI MIDDLEWARE
# =============================================================================


class TestRequestContextMiddleware:
    """Test FastAPI middleware."""

    @pytest.mark.asyncio
    async def test_middleware_extracts_request_id(self):
        """Test middleware extracts X-Request-ID from headers."""
        from manor.logger.context import RequestContextMiddleware, get_request_id
        
        # Mock ASGI app
        captured_request_id = None
        
        async def mock_app(scope, receive, send):
            nonlocal captured_request_id
            captured_request_id = get_request_id()
            
            # Send response
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            })
            await send({
                "type": "http.response.body",
                "body": b"OK",
            })
        
        middleware = RequestContextMiddleware(mock_app)
        
        # Create scope with X-Request-ID header
        scope = {
            "type": "http",
            "headers": [(b"x-request-id", b"incoming-request-123")],
        }
        
        # Track response headers
        response_headers = []
        
        async def receive():
            return {"type": "http.request", "body": b""}
        
        async def send(message):
            if message["type"] == "http.response.start":
                response_headers.extend(message.get("headers", []))
        
        await middleware(scope, receive, send)
        
        # Should have extracted the request ID
        assert captured_request_id == "incoming-request-123"
        
        # Should have added request ID to response
        response_header_dict = dict(response_headers)
        assert response_header_dict.get(b"x-request-id") == b"incoming-request-123"

    @pytest.mark.asyncio
    async def test_middleware_generates_request_id(self):
        """Test middleware generates request ID if not present."""
        from manor.logger.context import RequestContextMiddleware, get_request_id
        
        captured_request_id = None
        
        async def mock_app(scope, receive, send):
            nonlocal captured_request_id
            captured_request_id = get_request_id()
            
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            })
            await send({
                "type": "http.response.body",
                "body": b"OK",
            })
        
        middleware = RequestContextMiddleware(mock_app)
        
        # Scope without X-Request-ID
        scope = {
            "type": "http",
            "headers": [],
        }
        
        async def receive():
            return {"type": "http.request", "body": b""}
        
        async def send(message):
            pass
        
        await middleware(scope, receive, send)
        
        # Should have generated a request ID
        assert captured_request_id is not None
        assert len(captured_request_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_middleware_clears_context_after_request(self):
        """Test middleware clears context after request completes."""
        from manor.logger.context import RequestContextMiddleware, get_request_id
        
        async def mock_app(scope, receive, send):
            # Request ID should be set during request
            assert get_request_id() is not None
            
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            })
            await send({
                "type": "http.response.body",
                "body": b"OK",
            })
        
        middleware = RequestContextMiddleware(mock_app)
        
        scope = {
            "type": "http",
            "headers": [(b"x-request-id", b"test-123")],
        }
        
        async def receive():
            return {"type": "http.request", "body": b""}
        
        async def send(message):
            pass
        
        await middleware(scope, receive, send)
        
        # Context should be cleared after request
        assert get_request_id() is None

    @pytest.mark.asyncio
    async def test_middleware_skips_non_http(self):
        """Test middleware skips non-HTTP requests."""
        from manor.logger.context import RequestContextMiddleware, get_request_id
        
        app_called = False
        
        async def mock_app(scope, receive, send):
            nonlocal app_called
            app_called = True
        
        middleware = RequestContextMiddleware(mock_app)
        
        # WebSocket scope
        scope = {
            "type": "websocket",
            "headers": [],
        }
        
        async def receive():
            return {}
        
        async def send(message):
            pass
        
        await middleware(scope, receive, send)
        
        # App should still be called
        assert app_called
        
        # But no request ID should be set
        assert get_request_id() is None


# =============================================================================
# TESTS: DATADOG HANDLER
# =============================================================================


class TestDatadogHandler:
    """Test Datadog HTTP handler."""

    def test_handler_initialization(self, datadog_api_key):
        """Test handler initializes correctly."""
        from manor.logger.structured_logger import DatadogHttpHandler
        
        handler = DatadogHttpHandler(
            api_key=datadog_api_key,
            service="test-service",
            env="cicd",
            site="us5.datadoghq.com",
        )
        
        assert handler.service == "test-service"
        assert handler.env == "cicd"
        assert handler.batch_size == 10
        assert handler.flush_interval_seconds == 1.0
        
        # Cleanup
        handler.close()

    def test_handler_batches_logs(self, datadog_api_key, mock_httpx_client):
        """Test handler batches logs before sending."""
        from manor.logger.structured_logger import DatadogHttpHandler
        
        handler = DatadogHttpHandler(
            api_key=datadog_api_key,
            service="test-service",
            env="cicd",
            site="us5.datadoghq.com",
            batch_size=5,
        )
        
        # Create log records
        for i in range(3):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg=json.dumps({"msg": f"Test message {i}"}),
                args=(),
                exc_info=None,
            )
            handler.emit(record)
        
        # Should not have sent yet (batch size is 5)
        time.sleep(0.1)
        
        # Cleanup
        handler.close()

    def test_handler_flushes_on_batch_full(self, datadog_api_key, mock_httpx_client):
        """Test handler flushes when batch is full."""
        from manor.logger.structured_logger import DatadogHttpHandler
        
        handler = DatadogHttpHandler(
            api_key=datadog_api_key,
            service="test-service",
            env="cicd",
            site="us5.datadoghq.com",
            batch_size=3,
        )
        
        # Create enough log records to fill batch
        for i in range(3):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg=json.dumps({"msg": f"Test message {i}"}),
                args=(),
                exc_info=None,
            )
            handler.emit(record)
        
        # Give time for background thread to send
        time.sleep(0.5)
        
        # Should have called post
        assert mock_httpx_client.post.called
        
        # Cleanup
        handler.close()

    def test_handler_fork_safety(self, datadog_api_key):
        """Test handler detects PID change (simulated fork)."""
        from manor.logger.structured_logger import DatadogHttpHandler
        
        handler = DatadogHttpHandler(
            api_key=datadog_api_key,
            service="test-service",
            env="cicd",
            site="us5.datadoghq.com",
        )
        
        # Get initial client
        client1 = handler._get_http_client()
        
        # Simulate fork by changing stored PID
        handler._process_id = 99999
        
        # Get client again - should create new one
        client2 = handler._get_http_client()
        
        # Should be different clients
        assert client1 is not client2
        
        # Cleanup
        handler.close()


# =============================================================================
# TESTS: HEALTH CHECK FILTER
# =============================================================================


class TestHealthCheckFilter:
    """Test health check log filter."""

    def test_filter_blocks_health_logs(self):
        """Test filter blocks /health logs."""
        from manor.logger.structured_logger import HealthCheckLogFilter
        
        filter = HealthCheckLogFilter()
        
        # Create record with /health in message
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg='GET /health HTTP/1.1" 200',
            args=(),
            exc_info=None,
        )
        
        # Should be filtered out
        assert filter.filter(record) is False

    def test_filter_allows_other_logs(self):
        """Test filter allows non-health logs."""
        from manor.logger.structured_logger import HealthCheckLogFilter
        
        filter = HealthCheckLogFilter()
        
        # Create record without /health
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg='GET /api/users HTTP/1.1" 200',
            args=(),
            exc_info=None,
        )
        
        # Should be allowed
        assert filter.filter(record) is True


# =============================================================================
# TESTS: REAL DATADOG INTEGRATION
# =============================================================================


@pytest.mark.skipif(
    not os.getenv("DD_API_KEY"),
    reason="DD_API_KEY not set - skipping real Datadog tests"
)
class TestRealDatadogIntegration:
    """
    Integration tests that send real logs to Datadog.
    
    Run with:
        DD_API_KEY=your_api_key pytest tests/test_logger.py::TestRealDatadogIntegration -v
    
    Filter in Datadog:
        env:cicd service:manor-logger-test
    """

    def test_send_log_to_datadog(self, datadog_api_key, capsys):
        """Test sending a real log to Datadog using direct HTTP."""
        import httpx
        
        # Send directly via HTTP to avoid any singleton/mock issues
        intake_url = "https://http-intake.logs.us5.datadoghq.com/api/v2/logs"
        
        log_entry = {
            "message": "Integration test log from pytest",
            "service": "manor-logger-test",
            "ddsource": "python",
            "ddtags": "env:cicd,test_id:integration-test-001,test_type:automated,source:pytest",
            "hostname": "pytest-runner",
            "level": "info",
        }
        
        response = httpx.post(
            intake_url,
            json=[log_entry],
            headers={
                "Content-Type": "application/json",
                "DD-API-KEY": datadog_api_key,
            },
        )
        
        assert response.status_code == 202, f"Failed to send log: {response.text}"

    def test_send_multiple_logs_to_datadog(self, datadog_api_key):
        """Test sending multiple logs to Datadog using direct HTTP."""
        import httpx
        
        intake_url = "https://http-intake.logs.us5.datadoghq.com/api/v2/logs"
        
        logs = []
        for i in range(15):
            logs.append({
                "message": f"Batch test log {i} from pytest",
                "service": "manor-logger-test",
                "ddsource": "python",
                "ddtags": f"env:cicd,test_id:batch-test-001,log_number:{i}",
                "hostname": "pytest-runner",
                "level": "info",
            })
        
        response = httpx.post(
            intake_url,
            json=logs,
            headers={
                "Content-Type": "application/json",
                "DD-API-KEY": datadog_api_key,
            },
        )
        
        assert response.status_code == 202, f"Failed to send logs: {response.text}"

    def test_send_log_with_request_context(self, datadog_api_key):
        """Test sending log with request context to Datadog using direct HTTP."""
        import httpx
        
        intake_url = "https://http-intake.logs.us5.datadoghq.com/api/v2/logs"
        
        log_entry = {
            "message": "Request context test log from pytest",
            "service": "manor-logger-test",
            "ddsource": "python",
            "ddtags": "env:cicd,test_id:context-test-001,action:test_action",
            "hostname": "pytest-runner",
            "level": "info",
            "request_id": "test-request-abc-123",
            "user_id": "test-user-456",
            "tenant_id": "test-tenant-789",
        }
        
        response = httpx.post(
            intake_url,
            json=[log_entry],
            headers={
                "Content-Type": "application/json",
                "DD-API-KEY": datadog_api_key,
            },
        )
        
        assert response.status_code == 202, f"Failed to send log: {response.text}"

    def test_send_error_log_to_datadog(self, datadog_api_key):
        """Test sending error log to Datadog using direct HTTP."""
        import httpx
        
        intake_url = "https://http-intake.logs.us5.datadoghq.com/api/v2/logs"
        
        log_entry = {
            "message": "Error test log from pytest: Test exception for Datadog",
            "service": "manor-logger-test",
            "ddsource": "python",
            "ddtags": "env:cicd,test_id:error-test-001,error_type:ValueError",
            "hostname": "pytest-runner",
            "level": "error",
            "error": {
                "kind": "ValueError",
                "message": "Test exception for Datadog",
            },
        }
        
        response = httpx.post(
            intake_url,
            json=[log_entry],
            headers={
                "Content-Type": "application/json",
                "DD-API-KEY": datadog_api_key,
            },
        )
        
        assert response.status_code == 202, f"Failed to send log: {response.text}"
    
    def test_logger_handler_sends_to_datadog(self, datadog_api_key):
        """Test that the actual logger handler sends to Datadog."""
        from manor.logger.structured_logger import DatadogHttpHandler
        import logging
        
        # Create handler directly (no singleton issues)
        handler = DatadogHttpHandler(
            api_key=datadog_api_key,
            service="manor-logger-test",
            env="cicd",
            site="us5.datadoghq.com",
            batch_size=1,  # Flush immediately
            flush_interval_seconds=0.5,
        )
        handler.setLevel(logging.INFO)
        
        # Create and emit a log record
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=json.dumps({
                "msg": "Handler integration test from pytest",
                "test_id": "handler-test-001",
            }),
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        
        # Wait for background send
        time.sleep(2)
        
        # Cleanup
        handler.close()


# =============================================================================
# TESTS: THREAD SAFETY
# =============================================================================


class TestThreadSafety:
    """Test thread safety of logger components."""

    def test_concurrent_logging(self):
        """Test concurrent logging from multiple threads."""
        from manor.logger import configure_logging
        
        logger = configure_logging(service="thread-test", env="cicd")
        
        errors = []
        
        def log_from_thread(thread_id: int):
            try:
                for i in range(10):
                    logger.info(
                        f"Thread {thread_id} log {i}",
                        thread_id=thread_id,
                        log_number=i,
                    )
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=log_from_thread, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should have no errors
        assert len(errors) == 0

    def test_concurrent_context_isolation(self):
        """Test that context is isolated between threads."""
        from manor.logger.context import (
            set_request_id,
            get_request_id,
            clear_context,
        )
        
        results = {}
        
        def set_and_get_context(thread_id: int):
            request_id = f"thread-{thread_id}-request"
            set_request_id(request_id)
            
            # Small delay to allow other threads to interfere
            time.sleep(0.01)
            
            # Should still have our request ID
            results[thread_id] = get_request_id()
            
            clear_context()
        
        # Start multiple threads
        threads = []
        for i in range(10):
            t = threading.Thread(target=set_and_get_context, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Each thread should have gotten its own request ID
        for thread_id, result in results.items():
            assert result == f"thread-{thread_id}-request"


# =============================================================================
# TESTS: ASYNC CONTEXT ISOLATION
# =============================================================================


@pytest.mark.asyncio
class TestAsyncContextIsolation:
    """Test context isolation in async code."""

    async def test_concurrent_async_context(self):
        """Test context isolation between concurrent async tasks."""
        from manor.logger.context import (
            set_request_id,
            get_request_id,
            clear_context,
        )
        
        results = {}
        
        async def task_with_context(task_id: int):
            request_id = f"async-task-{task_id}"
            set_request_id(request_id)
            
            # Yield to other tasks
            await asyncio.sleep(0.01)
            
            # Should still have our request ID
            results[task_id] = get_request_id()
            
            clear_context()
        
        # Run multiple tasks concurrently
        await asyncio.gather(*[task_with_context(i) for i in range(10)])
        
        # Each task should have gotten its own request ID
        for task_id, result in results.items():
            assert result == f"async-task-{task_id}"
