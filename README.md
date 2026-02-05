# Manor Python Modules

Shared Python modules for Manor services.

## Installation

### With uv (recommended)

```bash
# Install latest version
uv add manor --find-links https://github.com/manor-tech/service-python-modules/releases/latest/download/
```

Or add to your `pyproject.toml`:

```toml
[tool.uv]
find-links = ["https://github.com/manor-tech/service-python-modules/releases/latest/download/"]

[project]
dependencies = ["manor"]
```

### Pin to specific version

```bash
# Install specific version
uv add manor==1.202502041530.42 --find-links https://github.com/manor-tech/service-python-modules/releases/download/v1.202502041530.42/
```

Or in `pyproject.toml`:

```toml
[tool.uv]
find-links = ["https://github.com/manor-tech/service-python-modules/releases/download/v1.202502041530.42/"]

[project]
dependencies = ["manor==1.202502041530.42"]
```

### Local Development

```bash
git clone https://github.com/manor-tech/service-python-modules.git
cd service-python-modules

# Install with uv
uv sync --all-groups

# Run tests
uv run pytest
```

## Modules

### Logger (`manor.logger`)

Structured logging with Datadog integration.

```python
from manor.logger import logger

# Structured logging
logger.info("Processing request", user_id="123", action="login")
logger.error("Payment failed", order_id="456", error="insufficient_funds")
```

See [manor/logger/README.md](manor/logger/README.md) for full documentation.

### Feature Flags (`manor.feature_flags`)

PostHog integration for feature flags.

```python
from manor.feature_flags import is_enabled, get_flag

# Simple boolean flag
if is_enabled("new-checkout"):
    use_new_checkout()

# With user targeting
if is_enabled("premium-feature", user_id="user-123"):
    show_premium_feature()

# Multivariate flag
variant = get_flag("checkout-experiment", user_id="user-123", default="control")
```

See [manor/feature_flags/README.md](manor/feature_flags/README.md) for full documentation.

### MCP Auth (`manor.mcp_auth`)

JWT authentication for MCP servers.

```python
from manor.mcp_auth import get_auth_headers
import httpx

# Get authentication headers
headers = get_auth_headers()

# Make authenticated request
response = httpx.get("http://service-search/mcp/tools", headers=headers)
```

See [manor/mcp_auth/README.md](manor/mcp_auth/README.md) for full documentation.

## Environment Variables

### Logger

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Log level | `INFO` |
| `DD_API_KEY` | Datadog API key | (none) |
| `DD_SITE` | Datadog site | `us5.datadoghq.com` |
| `DD_SERVICE` | Service name | `app` |
| `DD_ENV` | Environment | `dev` |

### Feature Flags

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTHOG_API_KEY` | PostHog API key | (required) |
| `POSTHOG_PERSONAL_API_KEY` | Enables local evaluation | (optional) |
| `POSTHOG_HOST` | PostHog host | `https://us.i.posthog.com` |

### MCP Auth

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_AUTH_SECRET` | Shared secret | (required) |
| `MCP_AUTH_ISSUER` | Token issuer | `manor-internal` |
| `MCP_AUTH_AUDIENCE` | Token audience | `service-search-mcp` |

## Development

```bash
# Install dependencies
uv sync --all-groups

# Run tests
uv run pytest -v

# Run linter
uv run ruff check .

# Format code
uv run ruff format .
```

## Publishing

Packages are automatically published as GitHub Releases on push to `main`:

- Version format: `1.TIMESTAMP.BUILD_NUMBER`
- Example: `1.202502041530.42`
- Releases: https://github.com/manor-tech/service-python-modules/releases
