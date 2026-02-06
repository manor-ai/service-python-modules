"""
Feature Flags client using PostHog.

USAGE:
    from manor.feature_flags import FeatureFlagChecker

    # Check a feature flag
    if FeatureFlagChecker.is_flag_enabled("my-feature"):
        # Feature is enabled
        do_new_thing()
    else:
        do_old_thing()

    # Or with instance
    checker = FeatureFlagChecker("my-feature")
    if checker.is_enabled():
        do_new_thing()

    # With user targeting
    if FeatureFlagChecker.is_flag_enabled("my-feature", user_id="user-123"):
        do_new_thing()

ENVIRONMENT VARIABLES:
    POSTHOG_API_KEY: Project API key (required)
    POSTHOG_PERSONAL_API_KEY: Feature flags secure API key (enables local evaluation)
    POSTHOG_HOST: PostHog host (default: https://us.i.posthog.com)
    POSTHOG_POLL_INTERVAL: Polling interval in seconds (default: 15)
    POSTHOG_DISTINCT_ID: Default distinct ID (default: SERVICE_NAME or "unknown-service")
    SERVICE_NAME: Service name used as fallback distinct ID
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

# =============================================================================
# STEP 1: CHECK OPTIONAL DEPENDENCIES
# =============================================================================

try:
    from posthog import Posthog
    POSTHOG_AVAILABLE = True
except ImportError:
    Posthog = None
    POSTHOG_AVAILABLE = False


# =============================================================================
# STEP 2: CONFIGURATION FROM ENVIRONMENT
# =============================================================================

# PostHog configuration
POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
POSTHOG_PERSONAL_API_KEY = os.getenv("POSTHOG_PERSONAL_API_KEY", "")
POSTHOG_HOST = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")
POSTHOG_POLL_INTERVAL = int(os.getenv("POSTHOG_POLL_INTERVAL", "15"))

# Default distinct ID for service-level flags
DEFAULT_DISTINCT_ID = os.getenv(
    "POSTHOG_DISTINCT_ID",
    os.getenv("SERVICE_NAME", "unknown-service"),
)


def _get_service_env():
    """Get service environment from ENVIRONMENT or DD_ENV, default to 'unknown'."""
    return os.getenv("ENVIRONMENT") or os.getenv("DD_ENV") or "unknown"


def _merge_properties(properties):
    """Merge user properties with default service_env."""
    default = {"service_env": _get_service_env()}
    if properties:
        default.update(properties)
    return default


# =============================================================================
# STEP 3: POSTHOG CLIENT (SINGLETON)
# =============================================================================


class PostHogClient:
    """
    Singleton PostHog client with automatic feature flag polling.

    WHAT IT DOES:
        - Connects to PostHog for feature flag evaluation
        - Supports local evaluation (faster) with personal API key
        - Polls for flag updates at configurable interval
        - Thread-safe singleton pattern

    USAGE:
        client = PostHogClient.get_instance()
        if client:
            enabled = client.feature_enabled("my-flag", "user-123")

    ENVIRONMENT VARIABLES:
        POSTHOG_API_KEY: Project API key (required)
        POSTHOG_PERSONAL_API_KEY: Enables local evaluation (optional but recommended)
        POSTHOG_HOST: PostHog host (default: https://us.i.posthog.com)
        POSTHOG_POLL_INTERVAL: Polling interval in seconds (default: 15)
    """

    # Singleton instance
    _instance: PostHogClient | None = None

    # Lock for thread-safe initialization
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """
        Initialize the PostHog client wrapper.

        NOTE: Do not call directly. Use PostHogClient.get_instance() instead.
        """
        self._client: Posthog | None = None
        self._initialized: bool = False

    @classmethod
    def get_instance(cls) -> PostHogClient | None:
        """
        Get or create the singleton PostHog client instance.

        THREAD SAFETY:
            Uses double-check locking to ensure only one instance is created
            even when called from multiple threads simultaneously.

        Returns:
            PostHogClient instance if successfully initialized, None otherwise.

        Example:
            client = PostHogClient.get_instance()
            if client:
                enabled = client.feature_enabled("my-flag", "user-123")
        """
        # Fast path: instance already exists
        if cls._instance is not None and cls._instance._client is not None:
            return cls._instance

        # Slow path: need to create instance
        with cls._lock:
            # Double-check after acquiring lock
            if cls._instance is None:
                cls._instance = PostHogClient()
                cls._instance._initialize()

        # Return instance only if client was successfully created
        if cls._instance._client is not None:
            return cls._instance

        return None

    @classmethod
    def shutdown(cls) -> None:
        """
        Shutdown the singleton PostHog client.

        Call this at application shutdown to cleanly close the client.
        """
        with cls._lock:
            if cls._instance is not None and cls._instance._client is not None:
                try:
                    cls._instance._client.shutdown()
                    sys.stderr.write("[FeatureFlags] Client shutdown\n")
                    sys.stderr.flush()
                except Exception:
                    pass
                cls._instance._client = None
            cls._instance = None

    def _initialize(self) -> None:
        """
        Initialize the PostHog client.

        This method is called automatically by get_instance().
        """
        # Prevent double initialization
        if self._initialized:
            return

        self._initialized = True

        # Check if PostHog library is available
        if not POSTHOG_AVAILABLE:
            sys.stderr.write(
                "[FeatureFlags] PostHog library not installed. "
                "Install with: pip install posthog\n"
            )
            sys.stderr.flush()
            return

        # Check for API key
        if not POSTHOG_API_KEY:
            sys.stderr.write(
                "[FeatureFlags] POSTHOG_API_KEY not set. "
                "Feature flags will be disabled.\n"
            )
            sys.stderr.flush()
            return

        # Create PostHog client
        try:
            self._client = Posthog(
                project_api_key=POSTHOG_API_KEY,
                host=POSTHOG_HOST,
                personal_api_key=POSTHOG_PERSONAL_API_KEY or None,
                poll_interval=POSTHOG_POLL_INTERVAL,
            )

            local_eval = bool(POSTHOG_PERSONAL_API_KEY)
            sys.stderr.write(
                f"[FeatureFlags] Client initialized "
                f"(host={POSTHOG_HOST}, "
                f"poll_interval={POSTHOG_POLL_INTERVAL}s, "
                f"local_evaluation={local_eval})\n"
            )
            sys.stderr.flush()

        except Exception as e:
            sys.stderr.write(f"[FeatureFlags] Failed to initialize: {e}\n")
            sys.stderr.flush()
            self._client = None

    def feature_enabled(
        self,
        flag_key: str,
        distinct_id: str,
        groups: dict[str, str] | None = None,
        person_properties: dict[str, Any] | None = None,
        group_properties: dict[str, dict[str, Any]] | None = None,
    ) -> bool | None:
        """
        Check if a feature flag is enabled for a user.

        Args:
            flag_key: The feature flag key
            distinct_id: User identifier for targeting
            groups: Optional group memberships (e.g., {"company": "acme"})
            person_properties: Optional user properties for targeting
            group_properties: Optional group properties for targeting

        Returns:
            True if enabled, False if disabled, None if error/unavailable

        Example:
            client = PostHogClient.get_instance()
            if client:
                enabled = client.feature_enabled(
                    "new-checkout",
                    "user-123",
                    person_properties={"plan": "premium"},
                )
        """
        if self._client is None:
            return None

        try:
            return self._client.feature_enabled(
                flag_key,
                distinct_id,
                groups=groups,
                person_properties=person_properties,
                group_properties=group_properties,
            )
        except Exception:
            return None

    def get_feature_flag(
        self,
        flag_key: str,
        distinct_id: str,
        groups: dict[str, str] | None = None,
        person_properties: dict[str, Any] | None = None,
        group_properties: dict[str, dict[str, Any]] | None = None,
    ) -> str | bool | None:
        """
        Get the value of a feature flag (for multivariate flags).

        Args:
            flag_key: The feature flag key
            distinct_id: User identifier for targeting
            groups: Optional group memberships
            person_properties: Optional user properties for targeting
            group_properties: Optional group properties for targeting

        Returns:
            The flag value (string for multivariate, bool for boolean, None if error)

        Example:
            client = PostHogClient.get_instance()
            if client:
                variant = client.get_feature_flag("checkout-variant", "user-123")
                if variant == "new":
                    show_new_checkout()
                elif variant == "control":
                    show_old_checkout()
        """
        if self._client is None:
            return None

        try:
            return self._client.get_feature_flag(
                flag_key,
                distinct_id,
                groups=groups,
                person_properties=person_properties,
                group_properties=group_properties,
            )
        except Exception:
            return None

    def get_all_flags(
        self,
        distinct_id: str,
        groups: dict[str, str] | None = None,
        person_properties: dict[str, Any] | None = None,
        group_properties: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, str | bool]:
        """
        Get all feature flags for a user.

        Returns:
            Dictionary of flag_key -> flag_value
        """
        if self._client is None:
            return {}

        try:
            return self._client.get_all_flags(
                distinct_id,
                groups=groups,
                person_properties=person_properties,
                group_properties=group_properties,
            )
        except Exception:
            return {}

    def capture(
        self,
        distinct_id: str,
        event: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Capture an event in PostHog.

        Useful for tracking feature flag usage and experiments.

        Args:
            distinct_id: User identifier
            event: Event name
            properties: Optional event properties
        """
        if self._client is None:
            return

        try:
            self._client.capture(
                distinct_id,
                event,
                properties=properties,
            )
        except Exception:
            pass


# =============================================================================
# STEP 4: FEATURE FLAG CHECKER (HIGH-LEVEL API)
# =============================================================================


class FeatureFlagChecker:
    """
    High-level helper class to check feature flags.

    USAGE:
        # Class method (simplest)
        if FeatureFlagChecker.is_flag_enabled("my-feature"):
            do_new_thing()

        # With user targeting
        if FeatureFlagChecker.is_flag_enabled("my-feature", user_id="user-123"):
            do_new_thing()

        # Instance method (for reuse)
        checker = FeatureFlagChecker("my-feature")
        if checker.is_enabled():
            do_new_thing()

        # Get multivariate flag value
        variant = FeatureFlagChecker.get_flag_value("checkout-variant", user_id="user-123")
        if variant == "new":
            show_new_checkout()

    LOGGING:
        All flag checks are logged for debugging and auditing.
    """

    def __init__(self, feature_flag: str) -> None:
        """
        Create a checker for a specific feature flag.

        Args:
            feature_flag: The feature flag key to check
        """
        self._feature_flag = feature_flag

    def is_enabled(
        self,
        user_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """
        Check if the feature flag is enabled.

        Args:
            user_id: Optional user identifier for targeting
            properties: Optional user properties for targeting

        Returns:
            True if enabled, False otherwise (including errors)
        """
        return self._check_flag(
            self._feature_flag,
            user_id=user_id,
            properties=properties,
        )

    @classmethod
    def is_flag_enabled(
        cls,
        feature_flag: str,
        user_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """
        Class method to check if a feature flag is enabled.

        Args:
            feature_flag: The feature flag key
            user_id: Optional user identifier for targeting
            properties: Optional user properties for targeting

        Returns:
            True if enabled, False otherwise (including errors)

        Example:
            if FeatureFlagChecker.is_flag_enabled("new-feature", user_id="user-123"):
                use_new_feature()
        """
        return cls._check_flag(
            feature_flag,
            user_id=user_id,
            properties=properties,
        )

    @classmethod
    def get_flag_value(
        cls,
        feature_flag: str,
        user_id: str | None = None,
        properties: dict[str, Any] | None = None,
        default: str | bool | None = None,
    ) -> str | bool | None:
        """
        Get the value of a feature flag (for multivariate flags).

        Args:
            feature_flag: The feature flag key
            user_id: Optional user identifier for targeting
            properties: Optional user properties for targeting
            default: Default value if flag not found or error

        Returns:
            The flag value (string for multivariate, bool for boolean)

        Example:
            variant = FeatureFlagChecker.get_flag_value(
                "checkout-experiment",
                user_id="user-123",
                default="control",
            )
        """
        client = PostHogClient.get_instance()
        if client is None:
            cls._log(
                "warning",
                "posthog_client_unavailable",
                feature_flag=feature_flag,
            )
            return default

        distinct_id = user_id or DEFAULT_DISTINCT_ID
        merged_properties = _merge_properties(properties)

        try:
            value = client.get_feature_flag(
                feature_flag,
                distinct_id,
                person_properties=merged_properties,
            )

            cls._log(
                "info",
                "posthog_feature_flag_value",
                feature_flag=feature_flag,
                value=value,
                distinct_id=distinct_id,
            )

            return value if value is not None else default

        except Exception as e:
            cls._log(
                "error",
                "posthog_feature_flag_error",
                feature_flag=feature_flag,
                error=str(e),
            )
            return default

    @classmethod
    def _check_flag(
        cls,
        feature_flag: str,
        user_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """
        Internal method to check a feature flag.

        Args:
            feature_flag: The feature flag key
            user_id: Optional user identifier
            properties: Optional user properties

        Returns:
            True if enabled, False otherwise
        """
        client = PostHogClient.get_instance()
        if client is None:
            cls._log(
                "warning",
                "posthog_client_unavailable",
                feature_flag=feature_flag,
            )
            return False

        distinct_id = user_id or DEFAULT_DISTINCT_ID
        merged_properties = _merge_properties(properties)

        try:
            enabled = client.feature_enabled(
                feature_flag,
                distinct_id,
                person_properties=merged_properties,
            )

            cls._log(
                "info",
                "posthog_feature_flag_checked",
                feature_flag=feature_flag,
                enabled=enabled,
                distinct_id=distinct_id,
            )

            return bool(enabled) if enabled is not None else False

        except Exception as e:
            cls._log(
                "error",
                "posthog_feature_flag_error",
                feature_flag=feature_flag,
                error=str(e),
            )
            return False

    @staticmethod
    def _log(level: str, message: str, **kwargs: Any) -> None:
        """
        Log a message, using manor.logger if available.

        Falls back to stderr if logger not available.
        """
        try:
            from manor.logger import logger
            log_method = getattr(logger, level, logger.info)
            log_method(message, **kwargs)
        except ImportError:
            # Fallback to stderr
            import json
            log_data = {"level": level, "msg": message, **kwargs}
            sys.stderr.write(json.dumps(log_data) + "\n")
            sys.stderr.flush()


# =============================================================================
# STEP 5: CONVENIENCE FUNCTIONS
# =============================================================================


def init_client() -> PostHogClient | None:
    """
    Initialize the global PostHog client.

    Call this at application startup.

    Returns:
        PostHogClient instance if successful, None otherwise
    """
    return PostHogClient.get_instance()


def shutdown_client() -> None:
    """
    Shutdown the global PostHog client.

    Call this at application shutdown.
    """
    PostHogClient.shutdown()


def get_client() -> PostHogClient | None:
    """
    Get the global PostHog client instance.

    Returns:
        PostHogClient instance if initialized, None otherwise
    """
    return PostHogClient.get_instance()


def is_enabled(
    flag_key: str,
    user_id: str | None = None,
    properties: dict[str, Any] | None = None,
) -> bool:
    """
    Check if a feature flag is enabled.

    Convenience function that wraps FeatureFlagChecker.

    Args:
        flag_key: The feature flag key
        user_id: Optional user identifier for targeting
        properties: Optional user properties for targeting

    Returns:
        True if enabled, False otherwise

    Example:
        from manor.feature_flags import is_enabled

        if is_enabled("new-checkout", user_id="user-123"):
            show_new_checkout()
    """
    return FeatureFlagChecker.is_flag_enabled(
        flag_key,
        user_id=user_id,
        properties=properties,
    )


def get_flag(
    flag_key: str,
    user_id: str | None = None,
    properties: dict[str, Any] | None = None,
    default: str | bool | None = None,
) -> str | bool | None:
    """
    Get the value of a feature flag.

    Convenience function for multivariate flags.

    Args:
        flag_key: The feature flag key
        user_id: Optional user identifier for targeting
        properties: Optional user properties for targeting
        default: Default value if flag not found

    Returns:
        The flag value

    Example:
        from manor.feature_flags import get_flag

        variant = get_flag("checkout-experiment", user_id="user-123", default="control")
    """
    return FeatureFlagChecker.get_flag_value(
        flag_key,
        user_id=user_id,
        properties=properties,
        default=default,
    )
