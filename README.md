# Manor Python Modules

Shared Python modules for Manor services.

## Installation

### From GitHub Packages (Production)

Add to your `requirements.txt`:

```
manor @ https://github.com/manor-tech/service-python-modules/releases/download/v0.1.0/manor-0.1.0-py3-none-any.whl
```

Or install directly with pip:

```bash
pip install manor --index-url https://pypi.pkg.github.com/manor-tech/ --extra-index-url https://pypi.org/simple/
```

### Authentication for GitHub Packages

For local development, configure pip to authenticate with GitHub:

```bash
# ~/.pip/pip.conf (Linux/macOS) or %APPDATA%\pip\pip.ini (Windows)
[global]
extra-index-url = https://__token__:${GITHUB_TOKEN}@pypi.pkg.github.com/manor-tech/
```

For Docker builds, use build args:

```dockerfile
ARG GITHUB_TOKEN
RUN pip install manor --index-url https://__token__:${GITHUB_TOKEN}@pypi.pkg.github.com/manor-tech/ --extra-index-url https://pypi.org/simple/
```

### Local Development

```bash
# Clone the repository
git clone https://github.com/manor-tech/service-python-modules.git
cd service-python-modules

# Install in editable mode
pip install -e ".[dev]"
```

## Modules

### Logger (`manor.logger`)

Structured logging with Datadog integration.

```python
from manor.logger import configure_logging, logger, log_datadog

# Configure structured logging
configure_logging(service_name="my-service")

# Use structured logger
logger.info("Processing request", user_id="123", action="login")

# Direct Datadog logging (for workers/Celery)
log_datadog("Task completed", level="info", task_id="abc")
```

### Feature Flags (`manor.feature_flags`)

LaunchDarkly integration for feature flags.

```python
from manor.feature_flags import init_client, get_flag, shutdown_client

# Initialize at app startup
init_client()

# Check feature flags
if get_flag("new-checkout-flow", user_key="user-123"):
    # New feature enabled for this user
    use_new_checkout()
else:
    use_legacy_checkout()

# With user attributes for targeting
enabled = get_flag(
    "premium-feature",
    user_key="user-123",
    user_attributes={"plan": "premium", "country": "BR"}
)

# Shutdown at app exit
shutdown_client()
```

#### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LAUNCHDARKLY_SDK_KEY` | LaunchDarkly SDK key | (required) |
| `LAUNCHDARKLY_OFFLINE` | Run in offline mode | `false` |
| `DD_ENV` / `ENVIRONMENT` | Environment name | `dev` |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check .

# Format code
ruff format .
```

## Publishing

Packages are automatically published to GitHub Packages when a tag is pushed:

```bash
git tag v0.1.0
git push origin v0.1.0
```
