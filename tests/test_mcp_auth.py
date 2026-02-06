"""
Tests for manor.mcp_auth module.

Run with:
    python3 -m pytest tests/test_mcp_auth.py -v
"""

import os
import threading
import time
from unittest import mock

import jwt
import pytest


# Reset singleton before and after each test
@pytest.fixture(autouse=True)
def reset_singleton():
    from manor.mcp_auth.token import MCPTokenProvider
    MCPTokenProvider._instance = None
    MCPTokenProvider._init_failed = False
    yield
    MCPTokenProvider._instance = None
    MCPTokenProvider._init_failed = False


# Mock feature flag to return True
@pytest.fixture
def mock_feature_flag():
    with mock.patch("manor.mcp_auth.token.MCPTokenProvider._is_feature_enabled") as m:
        m.return_value = True
        yield m


class TestImports:
    """Test that all exports are available."""
    
    def test_import_module(self):
        from manor import mcp_auth
        assert mcp_auth is not None
    
    def test_import_functions(self):
        from manor.mcp_auth import get_auth_headers, get_token, is_enabled
        assert callable(get_token)
        assert callable(get_auth_headers)
        assert callable(is_enabled)
    
    def test_import_class(self):
        from manor.mcp_auth import MCPTokenProvider
        assert MCPTokenProvider is not None


class TestMCPTokenProvider:
    """Test MCPTokenProvider class."""
    
    def test_get_instance_returns_singleton(self):
        from manor.mcp_auth import MCPTokenProvider
        
        instance1 = MCPTokenProvider.get_instance()
        instance2 = MCPTokenProvider.get_instance()
        
        assert instance1 is not None
        assert instance1 is instance2
    
    def test_get_config_defaults(self):
        from manor.mcp_auth import MCPTokenProvider
        
        with mock.patch.dict(os.environ, {}, clear=True):
            instance = MCPTokenProvider.get_instance()
            config = instance._get_config()
            
            assert config["secret"] == ""
            assert config["issuer"] == "manor-internal"
            assert config["audience"] == "service-search-mcp"
            assert config["ttl_seconds"] == 3600
            assert config["margin_seconds"] == 30
    
    def test_get_config_from_env(self):
        from manor.mcp_auth import MCPTokenProvider
        
        env = {
            "MCP_AUTH_SECRET": "test-secret",
            "MCP_AUTH_ISSUER": "test-issuer",
            "MCP_AUTH_AUDIENCE": "test-audience",
            "MCP_AUTH_SUBJECT": "test-subject",
            "MCP_AUTH_TTL_SECONDS": "7200",
            "MCP_AUTH_MARGIN_SECONDS": "60",
        }
        
        with mock.patch.dict(os.environ, env, clear=True):
            instance = MCPTokenProvider.get_instance()
            config = instance._get_config()
            
            assert config["secret"] == "test-secret"
            assert config["issuer"] == "test-issuer"
            assert config["audience"] == "test-audience"
            assert config["subject"] == "test-subject"
            assert config["ttl_seconds"] == 7200
            assert config["margin_seconds"] == 60


class TestTokenGeneration:
    """Test token generation."""
    
    def test_get_token_returns_none_without_secret(self, mock_feature_flag):
        from manor.mcp_auth import get_token
        
        with mock.patch.dict(os.environ, {"MCP_AUTH_SECRET": ""}, clear=True):
            token = get_token()
            assert token is None
    
    def test_get_token_generates_valid_jwt(self, mock_feature_flag):
        from manor.mcp_auth import get_token
        
        env = {
            "MCP_AUTH_SECRET": "test-secret-key",
            "MCP_AUTH_ISSUER": "test-issuer",
            "MCP_AUTH_AUDIENCE": "test-audience",
            "MCP_AUTH_SUBJECT": "test-subject",
        }
        
        with mock.patch.dict(os.environ, env, clear=True):
            token = get_token()
            
            assert token is not None
            
            # Decode and verify token
            payload = jwt.decode(
                token,
                "test-secret-key",
                algorithms=["HS256"],
                audience="test-audience",
            )
            
            assert payload["iss"] == "test-issuer"
            assert payload["aud"] == "test-audience"
            assert payload["sub"] == "test-subject"
            assert "exp" in payload
            assert "iat" in payload
    
    def test_get_token_returns_cached_token(self, mock_feature_flag):
        from manor.mcp_auth import get_token
        
        env = {
            "MCP_AUTH_SECRET": "test-secret-key",
            "MCP_AUTH_TTL_SECONDS": "3600",
            "MCP_AUTH_MARGIN_SECONDS": "30",
        }
        
        with mock.patch.dict(os.environ, env, clear=True):
            token1 = get_token()
            token2 = get_token()
            
            assert token1 == token2
    
    def test_get_token_refreshes_on_expiry(self, mock_feature_flag):
        from manor.mcp_auth import MCPTokenProvider
        
        env = {
            "MCP_AUTH_SECRET": "test-secret-key",
            "MCP_AUTH_TTL_SECONDS": "2",
            "MCP_AUTH_MARGIN_SECONDS": "1",
        }
        
        with mock.patch.dict(os.environ, env, clear=True):
            instance = MCPTokenProvider.get_instance()
            
            token1 = instance._get_token()
            time.sleep(1.5)
            token2 = instance._get_token()
            
            assert token1 != token2


class TestFeatureFlagIntegration:
    """Test feature flag integration."""
    
    def test_token_returns_none_when_flag_disabled(self):
        from manor.mcp_auth import get_token
        
        env = {"MCP_AUTH_SECRET": "test-secret"}
        
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("manor.mcp_auth.token.MCPTokenProvider._is_feature_enabled") as m:
                m.return_value = False
                token = get_token()
                assert token is None
    
    def test_token_generated_when_flag_enabled(self):
        from manor.mcp_auth import get_token
        
        env = {"MCP_AUTH_SECRET": "test-secret"}
        
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("manor.mcp_auth.token.MCPTokenProvider._is_feature_enabled") as m:
                m.return_value = True
                token = get_token()
                assert token is not None


class TestAuthHeaders:
    """Test get_auth_headers function."""
    
    def test_get_auth_headers_includes_bearer_token(self, mock_feature_flag):
        from manor.mcp_auth import get_auth_headers
        
        env = {"MCP_AUTH_SECRET": "test-secret"}
        
        with mock.patch.dict(os.environ, env, clear=True):
            headers = get_auth_headers()
            
            assert "Authorization" in headers
            assert headers["Authorization"].startswith("Bearer ")
    
    def test_get_auth_headers_returns_empty_dict_without_token(self):
        from manor.mcp_auth import get_auth_headers
        
        with mock.patch.dict(os.environ, {"MCP_AUTH_SECRET": ""}, clear=True):
            with mock.patch("manor.mcp_auth.token.MCPTokenProvider._is_feature_enabled") as m:
                m.return_value = False
                headers = get_auth_headers()
                assert headers == {}


class TestIsEnabled:
    """Test is_enabled function."""
    
    def test_is_enabled_returns_true_when_configured(self):
        from manor.mcp_auth import is_enabled
        
        env = {"MCP_AUTH_SECRET": "test-secret"}
        
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("manor.mcp_auth.token.MCPTokenProvider._is_feature_enabled") as m:
                m.return_value = True
                assert is_enabled() is True
    
    def test_is_enabled_returns_false_without_secret(self):
        from manor.mcp_auth import is_enabled
        
        with mock.patch.dict(os.environ, {"MCP_AUTH_SECRET": ""}, clear=True):
            with mock.patch("manor.mcp_auth.token.MCPTokenProvider._is_feature_enabled") as m:
                m.return_value = True
                assert is_enabled() is False
    
    def test_is_enabled_returns_false_when_flag_disabled(self):
        from manor.mcp_auth import is_enabled
        
        env = {"MCP_AUTH_SECRET": "test-secret"}
        
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("manor.mcp_auth.token.MCPTokenProvider._is_feature_enabled") as m:
                m.return_value = False
                assert is_enabled() is False


class TestThreadSafety:
    """Test thread safety of token provider."""
    
    def test_concurrent_get_instance_returns_same_instance(self, mock_feature_flag):
        from manor.mcp_auth import MCPTokenProvider
        
        instances = []
        errors = []
        
        def get_instance():
            try:
                instance = MCPTokenProvider.get_instance()
                instances.append(instance)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(instances) == 10
        assert all(i is instances[0] for i in instances)
    
    def test_concurrent_get_token_works(self, mock_feature_flag):
        from manor.mcp_auth import get_token
        
        env = {"MCP_AUTH_SECRET": "test-secret"}
        
        tokens = []
        errors = []
        
        def generate_token():
            try:
                token = get_token()
                tokens.append(token)
            except Exception as e:
                errors.append(e)
        
        with mock.patch.dict(os.environ, env, clear=True):
            threads = [threading.Thread(target=generate_token) for _ in range(10)]
            
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        
        assert len(errors) == 0
        assert len(tokens) == 10
        assert all(t is not None for t in tokens)


class TestJWTValidation:
    """Test JWT token validation (as would be done on server)."""
    
    def test_server_can_validate_token(self, mock_feature_flag):
        from manor.mcp_auth import get_token
        
        secret = "shared-secret-between-services"
        audience = "service-search-mcp"
        
        env = {
            "MCP_AUTH_SECRET": secret,
            "MCP_AUTH_AUDIENCE": audience,
            "MCP_AUTH_ISSUER": "manor-internal",
            "MCP_AUTH_SUBJECT": "service-application",
        }
        
        with mock.patch.dict(os.environ, env, clear=True):
            token = get_token()
            assert token is not None
            
            # Server validates token
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience=audience,
            )
            
            assert payload["iss"] == "manor-internal"
            assert payload["aud"] == audience
            assert payload["sub"] == "service-application"
            assert payload["exp"] > time.time()
    
    def test_wrong_secret_is_rejected(self, mock_feature_flag):
        from manor.mcp_auth import get_token
        
        env = {
            "MCP_AUTH_SECRET": "correct-secret",
            "MCP_AUTH_AUDIENCE": "test-audience",
        }
        
        with mock.patch.dict(os.environ, env, clear=True):
            token = get_token()
            
            with pytest.raises(jwt.InvalidSignatureError):
                jwt.decode(
                    token,
                    "wrong-secret",
                    algorithms=["HS256"],
                    audience="test-audience",
                )
    
    def test_wrong_audience_is_rejected(self, mock_feature_flag):
        from manor.mcp_auth import get_token
        
        env = {
            "MCP_AUTH_SECRET": "test-secret",
            "MCP_AUTH_AUDIENCE": "correct-audience",
        }
        
        with mock.patch.dict(os.environ, env, clear=True):
            token = get_token()
            
            with pytest.raises(jwt.InvalidAudienceError):
                jwt.decode(
                    token,
                    "test-secret",
                    algorithms=["HS256"],
                    audience="wrong-audience",
                )


class TestNeverRaises:
    """Test that the module NEVER raises exceptions."""
    
    def test_get_token_never_raises_with_invalid_env(self):
        from manor.mcp_auth import get_token
        
        # Invalid TTL value
        env = {
            "MCP_AUTH_SECRET": "test-secret",
            "MCP_AUTH_TTL_SECONDS": "not-a-number",
        }
        
        with mock.patch.dict(os.environ, env, clear=True):
            # Should not raise, should return None or valid token
            result = get_token()
            assert result is None or isinstance(result, str)
    
    def test_get_auth_headers_never_raises(self):
        from manor.mcp_auth import get_auth_headers
        
        # No config at all
        with mock.patch.dict(os.environ, {}, clear=True):
            result = get_auth_headers()
            assert isinstance(result, dict)
    
    def test_is_enabled_never_raises(self):
        from manor.mcp_auth import is_enabled
        
        # No config at all
        with mock.patch.dict(os.environ, {}, clear=True):
            result = is_enabled()
            assert result is False
    
    def test_get_token_returns_none_when_jwt_encode_fails(self, mock_feature_flag):
        from manor.mcp_auth import get_token
        from manor.mcp_auth.token import MCPTokenProvider
        
        env = {"MCP_AUTH_SECRET": "test-secret"}
        
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("jwt.encode", side_effect=Exception("JWT error")):
                # Reset singleton to force re-init
                MCPTokenProvider._instance = None
                result = get_token()
                assert result is None
    
    def test_get_auth_headers_returns_empty_on_any_error(self, mock_feature_flag):
        from manor.mcp_auth import get_auth_headers
        from manor.mcp_auth.token import MCPTokenProvider
        
        # Force get_token to raise
        with mock.patch.object(MCPTokenProvider, "get_token", side_effect=Exception("Unexpected")):
            result = get_auth_headers()
            assert result == {}
    
    def test_is_enabled_returns_false_on_any_error(self):
        from manor.mcp_auth import is_enabled
        from manor.mcp_auth.token import MCPTokenProvider
        
        # Force get_instance to raise
        with mock.patch.object(MCPTokenProvider, "get_instance", side_effect=Exception("Unexpected")):
            result = is_enabled()
            assert result is False
