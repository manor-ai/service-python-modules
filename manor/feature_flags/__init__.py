"""
Feature Flags module using PostHog.

USAGE:
    from manor.feature_flags import FeatureFlagChecker, is_enabled

    # Simple check
    if is_enabled("my-feature"):
        do_new_thing()

    # With user targeting
    if is_enabled("my-feature", user_id="user-123"):
        do_new_thing()

    # Using the checker class
    if FeatureFlagChecker.is_flag_enabled("my-feature"):
        do_new_thing()

    # Get multivariate flag value
    variant = get_flag("checkout-experiment", user_id="user-123", default="control")

ENVIRONMENT VARIABLES:
    POSTHOG_API_KEY: Project API key (required)
    POSTHOG_PERSONAL_API_KEY: Enables local evaluation (optional but recommended)
    POSTHOG_HOST: PostHog host (default: https://us.i.posthog.com)
    POSTHOG_POLL_INTERVAL: Polling interval in seconds (default: 15)
"""

from .client import (
    FeatureFlagChecker,
    PostHogClient,
    get_client,
    get_flag,
    init_client,
    is_enabled,
    shutdown_client,
)

__all__ = [
    # High-level API
    "FeatureFlagChecker",
    "is_enabled",
    "get_flag",
    # Client management
    "PostHogClient",
    "init_client",
    "shutdown_client",
    "get_client",
]
