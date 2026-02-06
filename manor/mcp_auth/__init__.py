"""
MCP Authentication module for Manor services.

Usage:
    from manor.mcp_auth import get_token, get_auth_headers

    # Get token directly
    token = get_token()
    if token:
        headers = {"Authorization": f"Bearer {token}"}

    # Or get headers directly
    headers = get_auth_headers()
    response = httpx.get("http://service-search/mcp", headers=headers)

    # Check if MCP auth is enabled
    if is_enabled():
        print("MCP auth is active")

Environment Variables:
    MCP_AUTH_SECRET: Shared secret for signing tokens (required)
    MCP_AUTH_ISSUER: Token issuer (default: manor-internal)
    MCP_AUTH_AUDIENCE: Token audience (default: service-search-mcp)
    MCP_AUTH_SUBJECT: Token subject (default: SERVICE_NAME)
    MCP_AUTH_TTL_SECONDS: Token TTL in seconds (default: 3600)
    MCP_AUTH_MARGIN_SECONDS: Refresh margin (default: 30)
    MCP_AUTH_FEATURE_FLAG: Feature flag key (default: manor_search_enable_mcp_api_token)
"""

from .token import MCPTokenProvider, get_auth_headers, get_token, is_enabled

__all__ = [
    "MCPTokenProvider",
    "get_token",
    "get_auth_headers",
    "is_enabled",
]
