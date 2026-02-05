# Manor MCP Authentication

JWT-based authentication for MCP (Model Context Protocol) servers.

## Overview

This module provides secure authentication between Manor services and MCP servers (like `service-search`). It generates JWT tokens that are:

- Signed with a shared secret (HS256)
- Cached and refreshed automatically
- Controlled by a feature flag for gradual rollout

## Installation

```bash
pip install manor
```

## Quick Start

```python
from manor.mcp_auth import get_auth_headers
import httpx

# Get authentication headers
headers = get_auth_headers()

# Make authenticated request to MCP server
response = httpx.get("http://service-search/mcp/tools", headers=headers)
```

## Configuration

All configuration is done via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_AUTH_SECRET` | Shared secret for signing tokens | (required) |
| `MCP_AUTH_ISSUER` | Token issuer claim | `manor-internal` |
| `MCP_AUTH_AUDIENCE` | Token audience claim | `service-search-mcp` |
| `MCP_AUTH_SUBJECT` | Token subject claim | `SERVICE_NAME` |
| `MCP_AUTH_TTL_SECONDS` | Token TTL in seconds | `3600` (1 hour) |
| `MCP_AUTH_MARGIN_SECONDS` | Refresh margin | `30` |
| `MCP_AUTH_FEATURE_FLAG` | Feature flag key | `manor_search_enable_api_token_v1` |

## Usage

### Get Token Directly

```python
from manor.mcp_auth import get_token

token = get_token()
if token:
    headers = {"Authorization": f"Bearer {token}"}
    # Make request with headers
```

### Get Auth Headers

```python
from manor.mcp_auth import get_auth_headers
import httpx

headers = get_auth_headers()
response = httpx.post(
    "http://service-search/mcp/invoke",
    headers=headers,
    json={"tool": "search", "args": {"query": "test"}},
)
```

### Check if Enabled

```python
from manor.mcp_auth import is_enabled

if is_enabled():
    print("MCP authentication is active")
else:
    print("MCP authentication is disabled")
```

### Using the Class Directly

```python
from manor.mcp_auth import MCPTokenProvider

# Get singleton instance
provider = MCPTokenProvider.get_instance()

# Get token
token = MCPTokenProvider.get_token()

# Get headers
headers = MCPTokenProvider.get_auth_headers()
```

## How It Works

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TOKEN GENERATION FLOW                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  get_token()                                                            │
│      │                                                                   │
│      ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  1. Check Feature Flag                                           │   │
│  │     - Is 'manor_search_enable_api_token_v1' enabled?             │   │
│  │     - If NO → return None                                        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│      │ YES                                                              │
│      ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  2. Check Configuration                                          │   │
│  │     - Is MCP_AUTH_SECRET set?                                    │   │
│  │     - If NO → return None                                        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│      │ YES                                                              │
│      ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  3. Check Cache                                                  │   │
│  │     - Is cached token still valid?                               │   │
│  │     - Valid = now < (token_exp - margin_seconds)                 │   │
│  │     - If YES → return cached token                               │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│      │ NO (expired or no cache)                                         │
│      ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  4. Generate New Token                                           │   │
│  │     - Create JWT with claims (iss, aud, sub, iat, exp)           │   │
│  │     - Sign with HS256 using MCP_AUTH_SECRET                      │   │
│  │     - Cache token and expiry                                     │   │
│  │     - Return new token                                           │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## JWT Token Structure

```json
{
  "iss": "manor-internal",
  "aud": "service-search-mcp",
  "sub": "service-application",
  "iat": 1704067200,
  "exp": 1704070800
}
```

| Claim | Description |
|-------|-------------|
| `iss` | Issuer - identifies the token generator |
| `aud` | Audience - identifies the intended recipient |
| `sub` | Subject - identifies the calling service |
| `iat` | Issued At - token creation timestamp |
| `exp` | Expiration - token expiry timestamp |

## Server-Side Validation

On the MCP server (e.g., `service-search`), validate tokens like this:

```python
import jwt
from fastapi import HTTPException, Header

MCP_AUTH_SECRET = os.getenv("MCP_AUTH_SECRET")
MCP_AUTH_AUDIENCE = "service-search-mcp"

def verify_mcp_token(authorization: str = Header(None)) -> dict:
    """Verify MCP authentication token."""
    if not authorization:
        raise HTTPException(401, "Missing authorization header")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization format")
    
    token = authorization[7:]  # Remove "Bearer " prefix
    
    try:
        payload = jwt.decode(
            token,
            MCP_AUTH_SECRET,
            algorithms=["HS256"],
            audience=MCP_AUTH_AUDIENCE,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, f"Invalid token: {e}")
```

## Feature Flag Integration

The module integrates with `manor.feature_flags` to control token generation:

```python
# Token is only generated if this flag is enabled
MCP_AUTH_FEATURE_FLAG = "manor_search_enable_api_token_v1"
```

This allows:
- Gradual rollout of authentication
- Easy disable in case of issues
- Per-user/per-service targeting

## Migration from Local Implementation

If migrating from a local `mcp_token.py`:

### Before (local)

```python
from app.utils.mcp_token import MCPTokenProvider

token = MCPTokenProvider.get_token()
```

### After (manor package)

```python
from manor.mcp_auth import get_token

token = get_token()
```

The API is compatible - just change the import!

## API Reference

### Functions

| Function | Description |
|----------|-------------|
| `get_token()` | Get JWT token (or None if disabled) |
| `get_auth_headers()` | Get dict with Authorization header |
| `is_enabled()` | Check if MCP auth is enabled |

### MCPTokenProvider Class

| Method | Description |
|--------|-------------|
| `get_instance()` | Get singleton instance |
| `get_token()` | Class method to get token |
| `get_auth_headers()` | Class method to get headers |

## Thread Safety

The `MCPTokenProvider` is thread-safe:
- Singleton uses double-check locking
- Token generation is protected by a lock
- Safe to use from multiple threads

## Error Handling

All errors are handled gracefully:
- If PyJWT not installed → returns None
- If feature flag disabled → returns None
- If secret not configured → returns None
- If token generation fails → returns None

The application continues to work even if MCP auth is unavailable.
