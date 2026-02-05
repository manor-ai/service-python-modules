# Manor Feature Flags

Feature flags module using PostHog for Manor services.

## Features

- **PostHog integration** with automatic feature flag polling
- **Local evaluation** support for faster flag checks
- **User targeting** with properties and groups
- **Multivariate flags** support
- **Automatic logging** of flag checks
- **Thread-safe singleton** pattern

## Installation

```bash
pip install manor
```

## Quick Start

```python
from manor.feature_flags import is_enabled

# Simple check
if is_enabled("new-checkout"):
    show_new_checkout()
else:
    show_old_checkout()
```

## Configuration

All configuration is done via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTHOG_API_KEY` | Project API key | (required) |
| `POSTHOG_PERSONAL_API_KEY` | Enables local evaluation | (optional) |
| `POSTHOG_HOST` | PostHog host | `https://us.i.posthog.com` |
| `POSTHOG_POLL_INTERVAL` | Polling interval (seconds) | `15` |
| `POSTHOG_DISTINCT_ID` | Default distinct ID | `SERVICE_NAME` |
| `SERVICE_NAME` | Service name (fallback) | `unknown-service` |

### Local Evaluation

For faster flag checks, set `POSTHOG_PERSONAL_API_KEY` with a personal API key from PostHog. This enables local evaluation without making API calls for each flag check.

## Usage

### Simple Boolean Flags

```python
from manor.feature_flags import is_enabled

if is_enabled("new-feature"):
    do_new_thing()
```

### User Targeting

```python
from manor.feature_flags import is_enabled

# Target specific user
if is_enabled("premium-feature", user_id="user-123"):
    show_premium_feature()

# With user properties
if is_enabled("beta-feature", user_id="user-123", properties={"plan": "premium"}):
    show_beta_feature()
```

### Multivariate Flags

```python
from manor.feature_flags import get_flag

variant = get_flag("checkout-experiment", user_id="user-123", default="control")

if variant == "new":
    show_new_checkout()
elif variant == "simplified":
    show_simplified_checkout()
else:
    show_old_checkout()
```

### Using FeatureFlagChecker Class

```python
from manor.feature_flags import FeatureFlagChecker

# Class method
if FeatureFlagChecker.is_flag_enabled("my-feature"):
    do_new_thing()

# Instance method (for reuse)
checker = FeatureFlagChecker("my-feature")
if checker.is_enabled():
    do_new_thing()

# With user targeting
if FeatureFlagChecker.is_flag_enabled("my-feature", user_id="user-123"):
    do_new_thing()
```

### Direct Client Access

```python
from manor.feature_flags import PostHogClient

client = PostHogClient.get_instance()
if client:
    # Check flag
    enabled = client.feature_enabled("my-flag", "user-123")
    
    # Get all flags for a user
    all_flags = client.get_all_flags("user-123")
    
    # Capture event
    client.capture("user-123", "feature_used", {"feature": "new-checkout"})
```

## Usage with FastAPI

### Basic Setup

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from manor.feature_flags import init_client, shutdown_client, is_enabled

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize feature flags
    init_client()
    yield
    # Shutdown: cleanup
    shutdown_client()

app = FastAPI(lifespan=lifespan)

@app.get("/checkout")
async def checkout(user_id: str):
    if is_enabled("new-checkout", user_id=user_id):
        return {"checkout": "new"}
    return {"checkout": "legacy"}
```

### With Dependency Injection

```python
from fastapi import FastAPI, Depends
from manor.feature_flags import FeatureFlagChecker

app = FastAPI()

def get_feature_checker():
    return FeatureFlagChecker

@app.get("/feature/{flag_key}")
async def check_feature(
    flag_key: str,
    user_id: str,
    checker: type[FeatureFlagChecker] = Depends(get_feature_checker),
):
    enabled = checker.is_flag_enabled(flag_key, user_id=user_id)
    return {"flag": flag_key, "enabled": enabled}
```

## Logging

All flag checks are automatically logged using `manor.logger`:

```json
{
  "msg": "posthog_feature_flag_checked",
  "level": "info",
  "feature_flag": "new-checkout",
  "enabled": true,
  "distinct_id": "user-123"
}
```

## Migration from Local Implementation

If you're migrating from a local `feature_flags.py` implementation:

### Before (local)

```python
from app.utils.feature_flags import FeatureFlagChecker

if FeatureFlagChecker.is_flag_enabled("my-feature"):
    do_new_thing()
```

### After (manor package)

```python
from manor.feature_flags import FeatureFlagChecker

if FeatureFlagChecker.is_flag_enabled("my-feature"):
    do_new_thing()
```

The API is identical - just change the import!

## API Reference

### Functions

| Function | Description |
|----------|-------------|
| `is_enabled(flag_key, user_id, properties)` | Check if flag is enabled |
| `get_flag(flag_key, user_id, properties, default)` | Get flag value |
| `init_client()` | Initialize PostHog client |
| `shutdown_client()` | Shutdown PostHog client |
| `get_client()` | Get PostHog client instance |

### Classes

| Class | Description |
|-------|-------------|
| `FeatureFlagChecker` | High-level flag checker |
| `PostHogClient` | Low-level PostHog client wrapper |

### FeatureFlagChecker Methods

| Method | Description |
|--------|-------------|
| `is_flag_enabled(flag, user_id, properties)` | Class method to check flag |
| `get_flag_value(flag, user_id, properties, default)` | Class method to get flag value |
| `is_enabled(user_id, properties)` | Instance method to check flag |

### PostHogClient Methods

| Method | Description |
|--------|-------------|
| `get_instance()` | Get singleton instance |
| `shutdown()` | Shutdown client |
| `feature_enabled(flag, distinct_id, ...)` | Check if flag enabled |
| `get_feature_flag(flag, distinct_id, ...)` | Get flag value |
| `get_all_flags(distinct_id, ...)` | Get all flags |
| `capture(distinct_id, event, properties)` | Capture event |

## Thread Safety

The `PostHogClient` uses a thread-safe singleton pattern with double-check locking. It's safe to use from multiple threads simultaneously.

## Error Handling

All errors are handled gracefully:
- If PostHog is unavailable, flags return `False` (or default value)
- Errors are logged but don't raise exceptions
- The application continues to work even if feature flags fail
