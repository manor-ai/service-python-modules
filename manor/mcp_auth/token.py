"""
MCP Authentication Token Provider.

Generates JWT tokens for authenticating with MCP servers (like service-search).

Usage:
    from manor.mcp_auth import get_token, get_auth_headers

    # Get a token
    token = get_token()
    if token:
        headers = {"Authorization": f"Bearer {token}"}

    # Or get headers directly
    headers = get_auth_headers()
    response = httpx.get(url, headers=headers)

Environment Variables:
    MCP_AUTH_SECRET: Shared secret for signing tokens (required)
    MCP_AUTH_ISSUER: Token issuer (default: manor-internal)
    MCP_AUTH_AUDIENCE: Token audience (default: service-search-mcp)
    MCP_AUTH_SUBJECT: Token subject (default: SERVICE_NAME or unknown-service)
    MCP_AUTH_TTL_SECONDS: Token TTL in seconds (default: 3600)
    MCP_AUTH_MARGIN_SECONDS: Refresh margin in seconds (default: 30)
    MCP_AUTH_FEATURE_FLAG: Feature flag key (default: manor_search_enable_api_token_v1)
"""

import os
import sys
import threading
import time

# Try to import PyJWT
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    jwt = None
    JWT_AVAILABLE = False


class MCPTokenProvider:
    """
    Singleton provider for MCP authentication tokens.
    
    Generates JWT tokens, caches them, and refreshes before expiry.
    Only generates tokens when feature flag is enabled.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        if not JWT_AVAILABLE:
            raise RuntimeError("PyJWT is required. Install with: pip install PyJWT")
        
        self._algorithm = "HS256"
        self._token = None
        self._token_exp = 0
        self._token_lock = threading.Lock()
    
    @classmethod
    def get_instance(cls):
        """Get or create the singleton instance."""
        if cls._instance is not None:
            return cls._instance
        
        with cls._lock:
            if cls._instance is None:
                try:
                    cls._instance = MCPTokenProvider()
                except RuntimeError as e:
                    sys.stderr.write(f"[MCPAuth] Failed to initialize: {e}\n")
                    sys.stderr.flush()
                    return None
        
        return cls._instance
    
    def _get_config(self):
        """Read configuration from environment variables."""
        return {
            "secret": os.getenv("MCP_AUTH_SECRET", ""),
            "issuer": os.getenv("MCP_AUTH_ISSUER", "manor-internal"),
            "audience": os.getenv("MCP_AUTH_AUDIENCE", "service-search-mcp"),
            "subject": os.getenv(
                "MCP_AUTH_SUBJECT",
                os.getenv("SERVICE_NAME", "unknown-service"),
            ),
            "ttl_seconds": int(os.getenv("MCP_AUTH_TTL_SECONDS", "3600")),
            "margin_seconds": int(os.getenv("MCP_AUTH_MARGIN_SECONDS", "30")),
            "feature_flag": os.getenv(
                "MCP_AUTH_FEATURE_FLAG",
                "manor_search_enable_api_token_v1",
            ),
        }
    
    def _is_feature_enabled(self, feature_flag):
        """Check if the MCP auth feature flag is enabled."""
        try:
            from manor.feature_flags import is_enabled
            return is_enabled(feature_flag)
        except ImportError:
            # Feature flags module not available, assume enabled
            return True
        except Exception:
            # Error checking flag, assume disabled for safety
            return False
    
    def _generate_token(self, config):
        """Generate a new JWT token."""
        now = int(time.time())
        exp = now + config["ttl_seconds"]
        
        payload = {
            "iss": config["issuer"],
            "aud": config["audience"],
            "sub": config["subject"],
            "iat": now,
            "exp": exp,
        }
        
        token = jwt.encode(payload, config["secret"], algorithm=self._algorithm)
        
        self._token = token
        self._token_exp = exp
        
        self._log(
            "info",
            "mcp_token_generated",
            issuer=config["issuer"],
            audience=config["audience"],
            subject=config["subject"],
            expires_at=exp,
            ttl_seconds=config["ttl_seconds"],
        )
        
        return token
    
    def _get_token(self):
        """Get a valid token, generating a new one if needed."""
        config = self._get_config()
        
        # Check feature flag first
        if not self._is_feature_enabled(config["feature_flag"]):
            return None
        
        # Check if secret is configured
        if not config["secret"]:
            self._log("warning", "mcp_token_missing_secret")
            return None
        
        # Thread-safe token generation
        with self._token_lock:
            now = int(time.time())
            margin = config["margin_seconds"]
            
            # Return cached token if still valid
            if self._token and now < (self._token_exp - margin):
                return self._token
            
            # Generate new token
            return self._generate_token(config)
    
    @classmethod
    def get_token(cls):
        """Get a valid MCP authentication token."""
        instance = cls.get_instance()
        if instance is None:
            return None
        return instance._get_token()
    
    @classmethod
    def get_auth_headers(cls):
        """Get authentication headers for MCP requests."""
        token = cls.get_token()
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}
    
    @staticmethod
    def _log(level, message, **kwargs):
        """Log a message using manor.logger if available."""
        try:
            from manor.logger import logger
            log_method = getattr(logger, level, logger.info)
            log_method(message, **kwargs)
        except ImportError:
            import json
            log_data = {"level": level, "msg": message, **kwargs}
            sys.stderr.write(json.dumps(log_data) + "\n")
            sys.stderr.flush()


# Convenience functions

def get_token():
    """Get a valid MCP authentication token."""
    return MCPTokenProvider.get_token()


def get_auth_headers():
    """Get authentication headers for MCP requests."""
    return MCPTokenProvider.get_auth_headers()


def is_enabled():
    """Check if MCP authentication is enabled."""
    instance = MCPTokenProvider.get_instance()
    if instance is None:
        return False
    
    config = instance._get_config()
    
    if not instance._is_feature_enabled(config["feature_flag"]):
        return False
    
    if not config["secret"]:
        return False
    
    return True
