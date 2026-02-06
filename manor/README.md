# Manor Python Modules

Shared Python modules for Manor services.

## Available Modules

| Module | Description |
|--------|-------------|
| `manor.logger` | Structured logging with Datadog integration |
| `manor.feature_flags` | Feature flags with PostHog |
| `manor.mcp_auth` | JWT authentication for MCP servers |

## Installation

### Using uv (recommended)

```bash
uv add manor --find-links https://github.com/manor-tech/service-python-modules/releases/latest/download/
```

### In pyproject.toml

```toml
[tool.uv]
find-links = ["https://github.com/manor-tech/service-python-modules/releases/latest/download/"]

[project]
dependencies = [
    "manor",
]
```

## Authentication for Private Repositories

Since the `service-python-modules` repository is private, you need to configure authentication with a GitHub Token.

### GitHub Actions

In your workflow, use the `GITHUB_TOKEN` that is already available:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        env:
          # Token to access releases from private repos
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # Configure authentication for GitHub
          gh auth setup-git
          
          # Install dependencies (including manor)
          uv sync
```

**Alternative using UV_EXTRA_INDEX_URL:**

```yaml
      - name: Install dependencies
        env:
          UV_EXTRA_INDEX_URL: https://${{ secrets.GITHUB_TOKEN }}@github.com/manor-tech/service-python-modules/releases/latest/download/
        run: uv sync
```

### Local Development

#### Option 1: Using gh CLI (recommended)

```bash
# Authenticate with GitHub CLI
gh auth login

# Configure git to use gh credentials
gh auth setup-git

# Now uv can access private releases
uv sync
```

#### Option 2: Using Personal Access Token (PAT)

1. Create a PAT at https://github.com/settings/tokens with `repo` permission

2. Configure in your environment:

```bash
# In ~/.bashrc or ~/.zshrc
export GITHUB_TOKEN="ghp_your_token_here"
```

3. Configure uv to use the token:

```bash
# In ~/.config/uv/uv.toml (Linux/macOS)
# Or %APPDATA%\uv\uv.toml (Windows)

[index]
extra-index-url = "https://${GITHUB_TOKEN}@github.com/"
```

#### Option 3: Using netrc

Create or edit `~/.netrc`:

```
machine github.com
login YOUR_GITHUB_USERNAME
password ghp_your_token_here
```

```bash
chmod 600 ~/.netrc
```

## Module Usage

### Logger

```python
from manor.logger import logger

# Simple logging
logger.info("Processing request", user_id="123")
logger.error("Payment failed", order_id="456", error="insufficient_funds")

# With request context (FastAPI)
from manor.logger import RequestContextMiddleware, get_correlation_headers

app.add_middleware(RequestContextMiddleware)

# Propagate to downstream services
headers = get_correlation_headers()
response = httpx.get("http://other-service/api", headers=headers)
```

**Environment variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Log level | `INFO` |
| `DD_API_KEY` | Datadog API key | (none) |
| `DD_SITE` | Datadog site | `us5.datadoghq.com` |
| `DD_SERVICE` | Service name | `app` |
| `DD_ENV` | Environment | `dev` |

### Feature Flags

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
if variant == "new":
    show_new_checkout()
```

**Environment variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTHOG_API_KEY` | PostHog API key | (required) |
| `POSTHOG_PERSONAL_API_KEY` | Enables local evaluation | (optional) |
| `POSTHOG_HOST` | PostHog host | `https://us.i.posthog.com` |

### MCP Auth

```python
from manor.mcp_auth import get_auth_headers, get_token, is_enabled
import httpx

# Get authentication headers
headers = get_auth_headers()

# Make authenticated request to MCP server
response = httpx.get("http://service-search/mcp/tools", headers=headers)

# Check if authentication is enabled
if is_enabled():
    print("MCP auth is active")
```

**Environment variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_AUTH_SECRET` | Shared secret | (required) |
| `MCP_AUTH_ISSUER` | Token issuer | `manor-internal` |
| `MCP_AUTH_AUDIENCE` | Token audience | `service-search-mcp` |
| `MCP_AUTH_SUBJECT` | Token subject | `SERVICE_NAME` |
| `MCP_AUTH_TTL_SECONDS` | Token TTL | `3600` |
| `MCP_AUTH_FEATURE_FLAG` | Feature flag | `manor_search_enable_mcp_api_token` |

## Complete Example: pyproject.toml

```toml
[project]
name = "my-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "manor",
    "fastapi",
    "uvicorn",
]

[tool.uv]
find-links = ["https://github.com/manor-tech/service-python-modules/releases/latest/download/"]
```

## Complete Example: GitHub Actions

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh auth setup-git
          uv sync

      - name: Run tests
        run: uv run pytest

      - name: Build
        run: docker build -t my-service .
```

## Dockerfile

```dockerfile
FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (needs token for private repos)
ARG GITHUB_TOKEN
RUN --mount=type=secret,id=github_token \
    GITHUB_TOKEN=$(cat /run/secrets/github_token) \
    uv sync --frozen --no-dev

# Copy code
COPY . .

CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build with token:

```bash
docker build --secret id=github_token,env=GITHUB_TOKEN -t my-service .
```

## Versioning

The package uses semantic versioning: `MAJOR.MINOR.BUILD`

- **MAJOR**: Breaking changes
- **MINOR**: New backward-compatible features
- **BUILD**: Build number (auto-incremented)

Example: `1.1.42`

## Links

- [Releases](https://github.com/manor-tech/service-python-modules/releases)
- [Logger README](logger/README.md)
- [Feature Flags README](feature_flags/README.md)
- [MCP Auth README](mcp_auth/README.md)
