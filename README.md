# Manor Python Modules

Shared Python modules for Manor services.

## Quick Install

```bash
uv add manor --find-links https://github.com/manor-tech/service-python-modules/releases/latest/download/
```

Or in `pyproject.toml`:

```toml
[tool.uv]
find-links = ["https://github.com/manor-tech/service-python-modules/releases/latest/download/"]

[project]
dependencies = ["manor"]
```

## Documentation

📖 **[See full documentation](manor/README.md)** - Includes:
- Detailed installation instructions
- Authentication for private repos (GitHub Actions and local)
- Usage examples for each module
- Docker configuration
- Environment variables

## Modules

| Module | Description | Docs |
|--------|-------------|------|
| `manor.logger` | Structured logging + Datadog | [README](manor/logger/README.md) |
| `manor.feature_flags` | Feature flags with PostHog | [README](manor/feature_flags/README.md) |
| `manor.mcp_auth` | JWT authentication for MCP | [README](manor/mcp_auth/README.md) |

## Quick Usage

```python
# Logger
from manor.logger import logger
logger.info("Hello", user_id="123")

# Feature Flags
from manor.feature_flags import is_enabled
if is_enabled("new-feature"):
    do_new_thing()

# MCP Auth
from manor.mcp_auth import get_auth_headers
headers = get_auth_headers()
```

## Development

```bash
git clone https://github.com/manor-tech/service-python-modules.git
cd service-python-modules

uv sync --all-groups
uv run pytest -v
```

## Releases

- **Format:** `MAJOR.MINOR.BUILD` (e.g., `1.1.42`)
- **URL:** https://github.com/manor-tech/service-python-modules/releases
