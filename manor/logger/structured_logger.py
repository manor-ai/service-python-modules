"""
Structured logging with Datadog integration.

USAGE:
    from manor.logger import logger
    logger.info("User logged in", user_id="123", action="login")

HOW IT WORKS:
    1. Logs are formatted as JSON using structlog
    2. Logs go to stdout (for container logs)
    3. Logs are also sent to Datadog via HTTP (if DD_API_KEY is set)
    4. Datadog trace IDs are automatically injected (if ddtrace is installed)

GUNICORN/FORK SAFETY:
    - Logger is initialized lazily (on first use, not on import)
    - HTTP client is recreated after fork (detects PID change)
    - Safe to use with: gunicorn --preload, uvicorn, or any WSGI/ASGI server
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
from typing import Any

import structlog


# =============================================================================
# STEP 1: CHECK OPTIONAL DEPENDENCIES
# =============================================================================
# These libraries are optional. The logger works without them.

# ddtrace: Datadog APM tracing (adds trace_id/span_id to logs)
try:
    from ddtrace import tracer
    DDTRACE_AVAILABLE = True
except ImportError:
    tracer = None
    DDTRACE_AVAILABLE = False

# httpx: HTTP client for sending logs to Datadog
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None
    HTTPX_AVAILABLE = False


# =============================================================================
# STEP 2: READ CONFIGURATION FROM ENVIRONMENT
# =============================================================================
# All configuration comes from environment variables with sensible defaults.

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Datadog configuration
DD_API_KEY = os.getenv("DD_API_KEY")  # Required for Datadog integration
DD_SITE = os.getenv("DD_SITE", "us5.datadoghq.com")  # Datadog region
DD_SERVICE = os.getenv("DD_SERVICE", "app")  # Service name in Datadog
DD_ENV = os.getenv("DD_ENV", os.getenv("ENVIRONMENT", "dev"))  # Environment tag

# Datadog HTTP intake URLs by region (for Logs API v2)
# Format: https://http-intake.logs.{site}
DD_INTAKE_URLS = {
    "datadoghq.com": "https://http-intake.logs.datadoghq.com",
    "datadoghq.eu": "https://http-intake.logs.datadoghq.eu",
    "us3.datadoghq.com": "https://http-intake.logs.us3.datadoghq.com",
    "us5.datadoghq.com": "https://http-intake.logs.us5.datadoghq.com",
    "ap1.datadoghq.com": "https://http-intake.logs.ap1.datadoghq.com",
}


# =============================================================================
# STEP 3: SINGLETON STATE
# =============================================================================
# These variables ensure the logger is configured only once, even in
# multi-threaded environments.

# The singleton logger instance (None until first use)
_logger_instance: structlog.stdlib.BoundLogger | None = None

# Lock for thread-safe initialization
_logger_lock = threading.Lock()

# Flag to track if configuration has been done
_is_configured = False


# =============================================================================
# STEP 4: DATADOG TRACE INJECTION
# =============================================================================
# This function adds Datadog trace context to every log entry.
# It allows correlating logs with APM traces in Datadog.


def add_datadog_trace_context(
    logger_instance: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """
    Add Datadog trace IDs to log entry.
    
    This is a structlog processor that runs for every log message.
    
    WHAT IT ADDS:
        - dd.trace_id: The current trace ID
        - dd.span_id: The current span ID
        - dd.service: The service name
        - dd.env: The environment
        - dd.version: The service version
    
    WHEN IT RUNS:
        Every time you call logger.info(), logger.error(), etc.
    
    Args:
        logger_instance: The structlog logger (unused but required by API)
        method_name: The log method called, e.g., "info" (unused)
        event_dict: The log data dictionary to enrich
    
    Returns:
        The enriched event_dict with trace context added
    """
    # Skip if ddtrace is not installed
    if not DDTRACE_AVAILABLE:
        return event_dict
    
    # Skip if tracer is not available
    if tracer is None:
        return event_dict
    
    # Try to get trace context from ddtrace
    try:
        trace_context = tracer.get_log_correlation_context()
        if trace_context:
            # Add all trace fields to the log entry
            # Example: {"dd.trace_id": "123", "dd.span_id": "456", ...}
            event_dict.update(trace_context)
    except Exception:
        # Never fail logging because of trace injection
        pass
    
    return event_dict


# =============================================================================
# STEP 5: DATADOG HTTP HANDLER
# =============================================================================
# This handler sends logs to Datadog via HTTP API.
# It batches logs for efficiency and sends them in background threads.


class DatadogHttpHandler(logging.Handler):
    """
    Logging handler that sends logs to Datadog via HTTP.
    
    FEATURES:
        - Batching: Collects logs and sends them in batches (default: 10)
        - Auto-flush: Sends logs every second even if batch is not full
        - Non-blocking: Sends logs in background threads
        - Fork-safe: Recreates HTTP client after process fork
    
    HOW IT WORKS:
        1. emit() is called for each log message
        2. Log is added to internal batch
        3. When batch is full OR 1 second passes:
           - Batch is sent to Datadog in a background thread
           - New batch starts collecting
    
    FORK SAFETY:
        When using Gunicorn with multiple workers, each worker is a separate
        process created via fork(). HTTP connections cannot be shared across
        fork boundaries. This handler detects fork by comparing PIDs and
        creates a new HTTP client in the child process.
    """

    def __init__(
        self,
        api_key: str,
        service: str,
        env: str,
        site: str,
        batch_size: int = 10,
        flush_interval_seconds: float = 1.0,
    ):
        """
        Initialize the Datadog handler.
        
        Args:
            api_key: Datadog API key (from DD_API_KEY env var)
            service: Service name for tagging logs
            env: Environment name (dev, staging, prod)
            site: Datadog site/region (e.g., us5.datadoghq.com)
            batch_size: Number of logs to collect before sending
            flush_interval_seconds: Max time to wait before sending
        """
        super().__init__()
        
        # Store configuration
        self.api_key = api_key
        self.service = service
        self.env = env
        self.site = site
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        
        # Build the Datadog intake URL (v2 API)
        base_url = DD_INTAKE_URLS.get(site, DD_INTAKE_URLS["datadoghq.com"])
        self.intake_url = f"{base_url}/api/v2/logs"
        
        # Batch storage: list of log entries waiting to be sent
        self._pending_logs: list[dict[str, Any]] = []
        
        # Lock for thread-safe access to _pending_logs
        self._batch_lock = threading.Lock()
        
        # Track when we last sent logs (for auto-flush timing)
        self._last_flush_time = time.monotonic()
        
        # Count consecutive errors (to avoid spamming stderr)
        self._consecutive_errors = 0
        
        # Fork detection: store current PID
        # If PID changes, we know we're in a forked child process
        self._process_id = os.getpid()
        
        # HTTP client (created lazily, recreated after fork)
        self._http_client: httpx.Client | None = None
        
        # Background flush thread control
        self._stop_flush_thread = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._background_flush_loop,
            daemon=True,  # Thread dies when main process exits
            name="datadog-log-flusher",
        )
        self._flush_thread.start()

    # -------------------------------------------------------------------------
    # HTTP Client Management (Fork-Safe)
    # -------------------------------------------------------------------------

    def _get_http_client(self) -> httpx.Client:
        """
        Get the HTTP client, creating a new one if needed.
        
        FORK SAFETY:
            After fork(), the child process has a copy of the parent's memory,
            including the HTTP client. But the underlying socket connections
            are shared with the parent, which causes problems.
            
            Solution: Detect fork by comparing PIDs. If PID changed, we're in
            a child process and must create a new HTTP client.
        
        Returns:
            An httpx.Client instance safe to use in the current process
        """
        current_pid = os.getpid()
        
        # Check if we're in a forked child process
        if self._process_id != current_pid:
            # PID changed = we were forked
            # Discard the old client (don't close it - parent owns it)
            self._http_client = None
            # Update our PID
            self._process_id = current_pid
        
        # Create client if we don't have one
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=5.0,  # 5 second timeout for requests
            )
        
        return self._http_client

    # -------------------------------------------------------------------------
    # Log Formatting
    # -------------------------------------------------------------------------

    def _convert_log_record_to_datadog_format(
        self,
        record: logging.LogRecord,
    ) -> dict[str, Any]:
        """
        Convert a Python log record to Datadog JSON format.
        
        INPUT (from structlog):
            LogRecord with message like:
            '{"msg": "User logged in", "user_id": "123", "level": "info"}'
        
        OUTPUT (for Datadog):
            {
                "message": "User logged in",
                "level": "info",
                "timestamp": 1234567890000,
                "service": "my-service",
                "ddsource": "python",
                "user_id": "123",
                "ddtags": "service:my-service,env:prod,user_id:123"
            }
        
        Args:
            record: Python logging.LogRecord from structlog
        
        Returns:
            Dictionary formatted for Datadog HTTP API
        """
        # Get the formatted message (JSON string from structlog)
        formatted_message = self.format(record)
        
        # Parse the JSON message
        try:
            log_data = json.loads(formatted_message)
        except (json.JSONDecodeError, TypeError):
            # If not JSON, wrap the raw message
            log_data = {"message": formatted_message}
        
        # Extract the main message (structlog uses "msg" key)
        main_message = log_data.pop("msg", None)
        if main_message is None:
            main_message = log_data.pop("message", formatted_message)
        
        # Extract log level
        log_level = log_data.pop("level", record.levelname.lower())
        
        # Remove timestamp (we'll use record.created instead)
        log_data.pop("timestamp", None)
        
        # Build the Datadog log entry
        datadog_entry: dict[str, Any] = {
            "message": main_message,
            "level": log_level,
            "timestamp": int(record.created * 1000),  # Milliseconds
            "service": self.service,
            "ddsource": "python",
            "logger": {
                "name": record.name,
            },
        }
        
        # Move Datadog trace fields (dd.*) to top level
        for key in list(log_data.keys()):
            if key.startswith("dd."):
                datadog_entry[key] = log_data.pop(key)
        
        # Build tags for Datadog facets
        tags = [
            f"service:{self.service}",
            f"env:{self.env}",
        ]
        
        # Add remaining fields as attributes and tags
        for key, value in log_data.items():
            if value is None:
                continue
            
            # Add to log entry
            if isinstance(value, (dict, list)):
                datadog_entry[key] = json.dumps(value)
            else:
                datadog_entry[key] = value
            
            # Add short values as tags (for Datadog facets)
            if len(str(value)) < 100:
                tags.append(f"{key}:{value}")
        
        # Join tags with commas
        datadog_entry["ddtags"] = ",".join(tags)
        
        return datadog_entry

    # -------------------------------------------------------------------------
    # Batch Sending
    # -------------------------------------------------------------------------

    def _send_pending_logs_to_datadog(self) -> None:
        """
        Send all pending logs to Datadog.
        
        MUST BE CALLED WITH self._batch_lock HELD.
        
        This method:
            1. Copies pending logs to a local variable
            2. Clears the pending logs list
            3. Spawns a background thread to send the logs
        
        The actual HTTP request happens in a background thread to avoid
        blocking the main application.
        """
        # Nothing to send
        if not self._pending_logs:
            return
        
        # Copy logs to send (we'll clear the pending list)
        logs_to_send = self._pending_logs.copy()
        self._pending_logs.clear()
        self._last_flush_time = time.monotonic()
        
        # Capture api_key for the background thread
        api_key = self.api_key
        intake_url = self.intake_url
        
        # Define the send function for the background thread
        def send_logs_in_background():
            try:
                client = self._get_http_client()
                response = client.post(
                    intake_url,
                    json=logs_to_send,
                    headers={
                        "Content-Type": "application/json",
                        "DD-API-KEY": api_key,
                    },
                )
                
                # v2 API returns 202 on success
                if response.status_code in (200, 202):
                    # Success - reset error counter
                    self._consecutive_errors = 0
                else:
                    # HTTP error
                    self._consecutive_errors += 1
                    if self._consecutive_errors <= 3:
                        sys.stderr.write(
                            f"Datadog HTTP error: {response.status_code} - {response.text}\n"
                        )
                        sys.stderr.flush()
                        
            except Exception as error:
                self._consecutive_errors += 1
                if self._consecutive_errors <= 3:
                    sys.stderr.write(f"Datadog send error: {error}\n")
                    sys.stderr.flush()
        
        # Send in background thread (non-blocking)
        thread = threading.Thread(
            target=send_logs_in_background,
            daemon=True,
            name="datadog-log-sender",
        )
        thread.start()

    def _background_flush_loop(self) -> None:
        """
        Background thread that periodically flushes logs.
        
        This ensures logs are sent even if the batch never fills up.
        Runs every flush_interval_seconds and sends any pending logs.
        """
        while not self._stop_flush_thread.is_set():
            # Sleep for the flush interval
            time.sleep(self.flush_interval_seconds)
            
            # Check if we have pending logs to send
            with self._batch_lock:
                if self._pending_logs:
                    self._send_pending_logs_to_datadog()

    # -------------------------------------------------------------------------
    # Logging Handler Interface
    # -------------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """
        Handle a log record.
        
        Called by Python's logging system for each log message.
        
        Args:
            record: The log record to handle
        """
        try:
            # Convert to Datadog format
            datadog_entry = self._convert_log_record_to_datadog_format(record)
            
            # Add to batch
            with self._batch_lock:
                self._pending_logs.append(datadog_entry)
                
                # Send if batch is full
                if len(self._pending_logs) >= self.batch_size:
                    self._send_pending_logs_to_datadog()
                    
        except Exception:
            # Never let logging errors crash the application
            pass

    def flush(self) -> None:
        """Force send all pending logs immediately."""
        with self._batch_lock:
            self._send_pending_logs_to_datadog()

    def close(self) -> None:
        """
        Clean up resources.
        
        Called when the handler is being shut down.
        """
        # Stop the background flush thread
        self._stop_flush_thread.set()
        self._flush_thread.join(timeout=2.0)
        
        # Send any remaining logs
        self.flush()
        
        # Close HTTP client
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
        
        super().close()


# =============================================================================
# STEP 6: HEALTH CHECK FILTER
# =============================================================================
# Filters out noisy health check logs from load balancers and Kubernetes.


class HealthCheckLogFilter(logging.Filter):
    """
    Filter that removes health check logs.
    
    WHY:
        Health checks (e.g., GET /health) happen every few seconds.
        They create noise in logs without providing useful information.
    
    WHAT IT FILTERS:
        Any log message containing "/health"
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Decide if a log record should be kept.
        
        Args:
            record: The log record to check
        
        Returns:
            True to keep the log, False to discard it
        """
        message = record.getMessage()
        
        # Discard if message contains /health
        if "/health" in message:
            return False
        
        # Keep all other logs
        return True


# =============================================================================
# STEP 7: MAIN CONFIGURATION FUNCTION
# =============================================================================
# This is the main entry point for configuring the logger.


def configure_logging(
    *,
    service: str | None = None,
    env: str | None = None,
    api_key: str | None = None,
    site: str | None = None,
) -> structlog.stdlib.BoundLogger:
    """
    Configure the logging system.
    
    This function sets up:
        1. Structured JSON logging via structlog
        2. Console output (stdout) for container logs
        3. Datadog HTTP logging (if DD_API_KEY is set)
        4. Async log processing via queue (non-blocking)
    
    SINGLETON BEHAVIOR:
        This function can be called multiple times safely.
        After the first call, subsequent calls return the same logger.
    
    THREAD SAFETY:
        Uses a lock to ensure only one thread configures the logger.
    
    Args:
        service: Service name (default: DD_SERVICE env var or "app")
        env: Environment (default: DD_ENV env var or "dev")
        api_key: Datadog API key (default: DD_API_KEY env var)
        site: Datadog site (default: DD_SITE env var or "us5.datadoghq.com")
    
    Returns:
        A configured structlog logger instance
    
    Example:
        logger = configure_logging(service="my-api", env="production")
        logger.info("Server started", port=8000)
    """
    global _logger_instance, _is_configured
    
    # ----- FAST PATH: Already configured -----
    # If already configured, return the existing logger immediately.
    # This check is outside the lock for performance.
    if _is_configured and _logger_instance is not None:
        return _logger_instance
    
    # ----- THREAD-SAFE INITIALIZATION -----
    # Only one thread should configure the logger.
    with _logger_lock:
        
        # Double-check after acquiring lock
        # Another thread might have configured while we waited
        if _is_configured and _logger_instance is not None:
            return _logger_instance
        
        # ----- RESOLVE CONFIGURATION -----
        # Use provided values or fall back to environment variables
        resolved_service = service if service is not None else DD_SERVICE
        resolved_env = env if env is not None else DD_ENV
        resolved_api_key = api_key if api_key is not None else DD_API_KEY
        resolved_site = site if site is not None else DD_SITE
        resolved_log_level = getattr(logging, LOG_LEVEL, logging.INFO)
        
        # ----- CREATE HANDLERS -----
        # Handlers determine where logs go
        handlers: list[logging.Handler] = []
        
        # Handler 1: Console (stdout)
        # All logs go to stdout for container logging
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(resolved_log_level)
        handlers.append(console_handler)
        
        # Handler 2: Datadog HTTP (optional)
        # Only enabled if DD_API_KEY is set and httpx is available
        if resolved_api_key and HTTPX_AVAILABLE:
            datadog_handler = DatadogHttpHandler(
                api_key=resolved_api_key,
                service=resolved_service,
                env=resolved_env,
                site=resolved_site,
                batch_size=10,
                flush_interval_seconds=1.0,
            )
            datadog_handler.setLevel(resolved_log_level)
            handlers.append(datadog_handler)
            
            # Ensure handler is closed on exit
            atexit.register(datadog_handler.close)
            
            sys.stderr.write(
                f"Datadog logging: ENABLED "
                f"(service={resolved_service}, env={resolved_env})\n"
            )
            sys.stderr.flush()
        else:
            if not resolved_api_key:
                sys.stderr.write("Datadog logging: DISABLED (DD_API_KEY not set)\n")
            elif not HTTPX_AVAILABLE:
                sys.stderr.write("Datadog logging: DISABLED (httpx not installed)\n")
            sys.stderr.flush()
        
        # ----- SETUP ASYNC LOGGING -----
        # Logs go through a queue to avoid blocking the application
        # 
        # Flow: logger.info() -> QueueHandler -> Queue -> QueueListener -> Handlers
        #
        # This makes logging non-blocking: the application just puts
        # the log in the queue and continues immediately.
        
        log_queue: Queue[logging.LogRecord] = Queue(maxsize=1000)
        
        # QueueHandler: Puts logs into the queue
        queue_handler = QueueHandler(log_queue)
        
        # QueueListener: Takes logs from queue and sends to handlers
        queue_listener = QueueListener(
            log_queue,
            *handlers,
            respect_handler_level=True,
        )
        queue_listener.start()
        
        # Ensure listener is stopped on exit
        atexit.register(queue_listener.stop)
        
        # ----- CONFIGURE ROOT LOGGER -----
        # All Python loggers inherit from the root logger
        logging.basicConfig(
            level=resolved_log_level,
            format="%(message)s",  # structlog handles formatting
            handlers=[queue_handler],
        )
        
        # ----- CONFIGURE THIRD-PARTY LOGGERS -----
        
        # Filter health checks from uvicorn access logs
        uvicorn_access_logger = logging.getLogger("uvicorn.access")
        uvicorn_access_logger.addFilter(HealthCheckLogFilter())
        
        # Reduce httpx noise (only warnings and above)
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.setLevel(logging.WARNING)
        
        # ----- CONFIGURE STRUCTLOG -----
        # structlog provides structured logging with key-value pairs
        #
        # Processors run in order for each log message:
        # 1. add_log_level: Add "level" field (info, error, etc.)
        # 2. TimeStamper: Add "timestamp" field (ISO format)
        # 3. inject_request_context: Add request_id and extra context
        # 4. add_datadog_trace_context: Add dd.trace_id, dd.span_id
        # 5. StackInfoRenderer: Add stack trace if requested
        # 6. format_exc_info: Format exception info
        # 7. UnicodeDecoder: Ensure strings are unicode
        # 8. EventRenamer: Rename "event" to "msg"
        # 9. JSONRenderer: Convert to JSON string
        
        # Import request context processor
        from manor.logger.context import inject_request_context
        
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                inject_request_context,
                add_datadog_trace_context,
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
        
        # ----- MARK AS CONFIGURED -----
        _is_configured = True
        _logger_instance = structlog.get_logger()
        
        sys.stderr.write(
            f"Logger: READY "
            f"(level={LOG_LEVEL}, ddtrace={DDTRACE_AVAILABLE})\n"
        )
        sys.stderr.flush()
        
        return _logger_instance


# =============================================================================
# STEP 8: LAZY LOGGER PROXY
# =============================================================================
# This allows importing `logger` without triggering configuration.
# Configuration happens on first actual use.


class LazyLoggerProxy:
    """
    A proxy that delays logger initialization until first use.
    
    WHY LAZY INITIALIZATION:
        1. Import time: Importing the module should be fast and side-effect free
        2. Fork safety: With Gunicorn --preload, code runs before fork.
           If we configure the logger at import time, the HTTP client
           would be created in the parent process and shared (incorrectly)
           with child workers.
        3. Flexibility: Allows calling configure_logging() with custom
           parameters before the first log.
    
    HOW IT WORKS:
        When you do `logger.info("Hello")`:
        1. Python calls LazyLoggerProxy.__getattr__("info")
        2. __getattr__ calls configure_logging() to get the real logger
        3. __getattr__ returns the "info" method from the real logger
        4. Python calls that method with "Hello"
    
    USAGE:
        from manor.logger import logger
        logger.info("This triggers configuration")
    """

    def __getattr__(self, attribute_name: str) -> Any:
        """
        Get an attribute from the real logger.
        
        This method is called when accessing any attribute on the proxy.
        It initializes the logger (if needed) and returns the attribute.
        
        Args:
            attribute_name: Name of the attribute (e.g., "info", "error")
        
        Returns:
            The attribute from the real logger
        """
        # Get or create the real logger
        real_logger = configure_logging()
        
        # Return the requested attribute from the real logger
        return getattr(real_logger, attribute_name)


# =============================================================================
# STEP 9: MODULE EXPORTS
# =============================================================================
# These are the public interfaces of this module.

# The lazy logger proxy - use this for logging
# Example: logger.info("Hello", user_id="123")
logger = LazyLoggerProxy()
