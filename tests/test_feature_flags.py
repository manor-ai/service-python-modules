"""
Tests for manor.feature_flags module.

Run with:
    pytest tests/test_feature_flags.py -v

Run with real PostHog integration:
    POSTHOG_API_KEY=your_key pytest tests/test_feature_flags.py -v
"""

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_posthog_client():
    """Reset PostHog client singleton state before each test."""
    from manor.feature_flags.client import PostHogClient
    
    # Reset singleton
    with PostHogClient._lock:
        if PostHogClient._instance is not None:
            try:
                if PostHogClient._instance._client is not None:
                    PostHogClient._instance._client = None
            except Exception:
                pass
            PostHogClient._instance = None
    
    yield
    
    # Cleanup after test
    with PostHogClient._lock:
        if PostHogClient._instance is not None:
            try:
                if PostHogClient._instance._client is not None:
                    PostHogClient._instance._client = None
            except Exception:
                pass
            PostHogClient._instance = None


@pytest.fixture
def mock_posthog():
    """Mock PostHog client for testing without real API calls."""
    with patch("manor.feature_flags.client.Posthog") as mock:
        mock_instance = MagicMock()
        mock_instance.feature_enabled.return_value = True
        mock_instance.get_feature_flag.return_value = "variant-a"
        mock_instance.get_all_flags.return_value = {"flag1": True, "flag2": "variant-b"}
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def posthog_api_key():
    """Get PostHog API key from environment."""
    return os.getenv("POSTHOG_API_KEY", "")


# =============================================================================
# TESTS: IMPORTS
# =============================================================================


class TestImports:
    """Test that all exports are available."""

    def test_import_feature_flag_checker(self):
        """Test FeatureFlagChecker can be imported."""
        from manor.feature_flags import FeatureFlagChecker
        assert FeatureFlagChecker is not None

    def test_import_posthog_client(self):
        """Test PostHogClient can be imported."""
        from manor.feature_flags import PostHogClient
        assert PostHogClient is not None

    def test_import_is_enabled(self):
        """Test is_enabled function can be imported."""
        from manor.feature_flags import is_enabled
        assert callable(is_enabled)

    def test_import_get_flag(self):
        """Test get_flag function can be imported."""
        from manor.feature_flags import get_flag
        assert callable(get_flag)

    def test_import_init_client(self):
        """Test init_client function can be imported."""
        from manor.feature_flags import init_client
        assert callable(init_client)

    def test_import_shutdown_client(self):
        """Test shutdown_client function can be imported."""
        from manor.feature_flags import shutdown_client
        assert callable(shutdown_client)

    def test_import_get_client(self):
        """Test get_client function can be imported."""
        from manor.feature_flags import get_client
        assert callable(get_client)


# =============================================================================
# TESTS: POSTHOG CLIENT SINGLETON
# =============================================================================


class TestPostHogClientSingleton:
    """Test PostHogClient singleton behavior."""

    def test_get_instance_returns_none_without_api_key(self):
        """Test that get_instance returns None without API key."""
        from manor.feature_flags import PostHogClient
        
        # Ensure no API key is set
        with patch.dict(os.environ, {"POSTHOG_API_KEY": ""}, clear=False):
            # Need to reimport to pick up env change
            import manor.feature_flags.client as client_module
            original_key = client_module.POSTHOG_API_KEY
            client_module.POSTHOG_API_KEY = ""
            
            try:
                instance = PostHogClient.get_instance()
                assert instance is None
            finally:
                client_module.POSTHOG_API_KEY = original_key

    def test_get_instance_returns_same_instance(self, mock_posthog):
        """Test that get_instance returns the same instance."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            instance1 = PostHogClient.get_instance()
            instance2 = PostHogClient.get_instance()
            
            assert instance1 is instance2
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_shutdown_clears_instance(self, mock_posthog):
        """Test that shutdown clears the singleton instance."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            # Get instance
            instance = PostHogClient.get_instance()
            assert instance is not None
            
            # Shutdown
            PostHogClient.shutdown()
            
            # Instance should be cleared
            assert PostHogClient._instance is None
        finally:
            client_module.POSTHOG_API_KEY = original_key


# =============================================================================
# TESTS: POSTHOG CLIENT METHODS
# =============================================================================


class TestPostHogClientMethods:
    """Test PostHogClient methods."""

    def test_feature_enabled(self, mock_posthog):
        """Test feature_enabled method."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            client = PostHogClient.get_instance()
            assert client is not None
            
            result = client.feature_enabled("test-flag", "user-123")
            
            assert result is True
            mock_posthog.feature_enabled.assert_called_once_with(
                "test-flag",
                "user-123",
                groups=None,
                person_properties=None,
                group_properties=None,
            )
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_feature_enabled_with_properties(self, mock_posthog):
        """Test feature_enabled with person properties."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            client = PostHogClient.get_instance()
            assert client is not None
            
            result = client.feature_enabled(
                "test-flag",
                "user-123",
                person_properties={"plan": "premium"},
            )
            
            assert result is True
            mock_posthog.feature_enabled.assert_called_with(
                "test-flag",
                "user-123",
                groups=None,
                person_properties={"plan": "premium"},
                group_properties=None,
            )
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_get_feature_flag(self, mock_posthog):
        """Test get_feature_flag method for multivariate flags."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            client = PostHogClient.get_instance()
            assert client is not None
            
            result = client.get_feature_flag("test-flag", "user-123")
            
            assert result == "variant-a"
            mock_posthog.get_feature_flag.assert_called_once()
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_get_all_flags(self, mock_posthog):
        """Test get_all_flags method."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            client = PostHogClient.get_instance()
            assert client is not None
            
            result = client.get_all_flags("user-123")
            
            assert result == {"flag1": True, "flag2": "variant-b"}
            mock_posthog.get_all_flags.assert_called_once()
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_capture_event(self, mock_posthog):
        """Test capture method."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            client = PostHogClient.get_instance()
            assert client is not None
            
            client.capture("user-123", "button_clicked", {"button": "checkout"})
            
            mock_posthog.capture.assert_called_once_with(
                "user-123",
                "button_clicked",
                properties={"button": "checkout"},
            )
        finally:
            client_module.POSTHOG_API_KEY = original_key


# =============================================================================
# TESTS: FEATURE FLAG CHECKER
# =============================================================================


class TestFeatureFlagChecker:
    """Test FeatureFlagChecker class."""

    def test_is_flag_enabled_class_method(self, mock_posthog):
        """Test is_flag_enabled class method."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            result = FeatureFlagChecker.is_flag_enabled("test-flag")
            
            assert result is True
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_is_flag_enabled_with_user_id(self, mock_posthog):
        """Test is_flag_enabled with user_id."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            result = FeatureFlagChecker.is_flag_enabled(
                "test-flag",
                user_id="user-123",
            )
            
            assert result is True
            # service_env is automatically added by _merge_properties
            mock_posthog.feature_enabled.assert_called_with(
                "test-flag",
                "user-123",
                groups=None,
                person_properties={"service_env": "unknown"},
                group_properties=None,
            )
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_is_flag_enabled_with_properties(self, mock_posthog):
        """Test is_flag_enabled with properties."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            result = FeatureFlagChecker.is_flag_enabled(
                "test-flag",
                user_id="user-123",
                properties={"plan": "premium"},
            )
            
            assert result is True
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_is_enabled_instance_method(self, mock_posthog):
        """Test is_enabled instance method."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            checker = FeatureFlagChecker("test-flag")
            result = checker.is_enabled()
            
            assert result is True
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_is_enabled_instance_with_user_id(self, mock_posthog):
        """Test is_enabled instance method with user_id."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            checker = FeatureFlagChecker("test-flag")
            result = checker.is_enabled(user_id="user-456")
            
            assert result is True
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_get_flag_value(self, mock_posthog):
        """Test get_flag_value class method."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            result = FeatureFlagChecker.get_flag_value("test-flag", user_id="user-123")
            
            assert result == "variant-a"
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_get_flag_value_with_default(self, mock_posthog):
        """Test get_flag_value returns default when flag not found."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        # Make mock return None
        mock_posthog.get_feature_flag.return_value = None
        
        try:
            result = FeatureFlagChecker.get_flag_value(
                "test-flag",
                user_id="user-123",
                default="control",
            )
            
            assert result == "control"
        finally:
            client_module.POSTHOG_API_KEY = original_key


# =============================================================================
# TESTS: CONVENIENCE FUNCTIONS
# =============================================================================


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_is_enabled_function(self, mock_posthog):
        """Test is_enabled function."""
        from manor.feature_flags import is_enabled
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            result = is_enabled("test-flag")
            
            assert result is True
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_is_enabled_with_user_id(self, mock_posthog):
        """Test is_enabled function with user_id."""
        from manor.feature_flags import is_enabled
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            result = is_enabled("test-flag", user_id="user-123")
            
            assert result is True
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_get_flag_function(self, mock_posthog):
        """Test get_flag function."""
        from manor.feature_flags import get_flag
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            result = get_flag("test-flag", user_id="user-123")
            
            assert result == "variant-a"
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_get_flag_with_default(self, mock_posthog):
        """Test get_flag function with default."""
        from manor.feature_flags import get_flag
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        mock_posthog.get_feature_flag.return_value = None
        
        try:
            result = get_flag("test-flag", default="control")
            
            assert result == "control"
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_init_client_function(self, mock_posthog):
        """Test init_client function."""
        from manor.feature_flags import init_client, get_client
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            client = init_client()
            
            assert client is not None
            assert get_client() is client
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_shutdown_client_function(self, mock_posthog):
        """Test shutdown_client function."""
        from manor.feature_flags import init_client, shutdown_client, get_client
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            init_client()
            shutdown_client()
            
            # After shutdown, get_client should return None
            # (but we need to reset the singleton first)
            from manor.feature_flags.client import PostHogClient
            assert PostHogClient._instance is None
        finally:
            client_module.POSTHOG_API_KEY = original_key


# =============================================================================
# TESTS: ERROR HANDLING
# =============================================================================


class TestErrorHandling:
    """Test error handling."""

    def test_is_enabled_returns_false_without_client(self):
        """Test is_enabled returns False when client unavailable."""
        from manor.feature_flags import is_enabled
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = ""
        
        try:
            result = is_enabled("test-flag")
            
            assert result is False
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_get_flag_returns_default_without_client(self):
        """Test get_flag returns default when client unavailable."""
        from manor.feature_flags import get_flag
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = ""
        
        try:
            result = get_flag("test-flag", default="fallback")
            
            assert result == "fallback"
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_feature_enabled_handles_exception(self, mock_posthog):
        """Test feature_enabled handles exceptions gracefully."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        mock_posthog.feature_enabled.side_effect = Exception("API error")
        
        try:
            client = PostHogClient.get_instance()
            result = client.feature_enabled("test-flag", "user-123")
            
            assert result is None
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_checker_handles_exception(self, mock_posthog):
        """Test FeatureFlagChecker handles exceptions gracefully."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        mock_posthog.feature_enabled.side_effect = Exception("API error")
        
        try:
            result = FeatureFlagChecker.is_flag_enabled("test-flag")
            
            assert result is False
        finally:
            client_module.POSTHOG_API_KEY = original_key


# =============================================================================
# TESTS: THREAD SAFETY
# =============================================================================


class TestThreadSafety:
    """Test thread safety."""

    def test_concurrent_get_instance(self, mock_posthog):
        """Test concurrent calls to get_instance."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        instances = []
        errors = []
        
        def get_instance():
            try:
                instance = PostHogClient.get_instance()
                instances.append(instance)
            except Exception as e:
                errors.append(e)
        
        try:
            threads = [threading.Thread(target=get_instance) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            assert len(errors) == 0
            assert len(instances) == 10
            # All instances should be the same (singleton)
            assert all(i is instances[0] for i in instances)
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_concurrent_is_enabled(self, mock_posthog):
        """Test concurrent calls to is_enabled."""
        from manor.feature_flags import is_enabled
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        results = []
        errors = []
        
        def check_flag(flag_num):
            try:
                result = is_enabled(f"flag-{flag_num}", user_id=f"user-{flag_num}")
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        try:
            threads = [threading.Thread(target=check_flag, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            assert len(errors) == 0
            assert len(results) == 20
            assert all(r is True for r in results)
        finally:
            client_module.POSTHOG_API_KEY = original_key


# =============================================================================
# TESTS: COMPATIBILITY WITH SERVICE-APPLICATION
# =============================================================================


class TestServiceApplicationCompatibility:
    """Test compatibility with service-application patterns."""

    def test_feature_flag_checker_pattern(self, mock_posthog):
        """Test the FeatureFlagChecker pattern used in service-application."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            # Pattern 1: Class method
            if FeatureFlagChecker.is_flag_enabled("my_feature"):
                pass  # Feature enabled
            
            # Pattern 2: Instance method
            checker = FeatureFlagChecker("my_feature")
            if checker.is_enabled():
                pass  # Feature enabled
            
            # Both patterns should work
            assert FeatureFlagChecker.is_flag_enabled("my_feature") is True
            assert checker.is_enabled() is True
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_posthog_client_pattern(self, mock_posthog):
        """Test the PostHogClient pattern used in service-application."""
        from manor.feature_flags import PostHogClient
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        try:
            # Pattern from service-application
            client = PostHogClient.get_instance()
            if client:
                enabled = client.feature_enabled("my_flag", "user_id")
                assert enabled is True
        finally:
            client_module.POSTHOG_API_KEY = original_key

    def test_feature_flag_key_constant_pattern(self, mock_posthog):
        """Test using feature flag key constants."""
        from manor.feature_flags import FeatureFlagChecker
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = "test-api-key"
        
        # Pattern from service-application
        FEATURE_FLAG_KEY_MY_FEATURE = "my_feature_v1"
        
        try:
            result = FeatureFlagChecker.is_flag_enabled(FEATURE_FLAG_KEY_MY_FEATURE)
            assert result is True
        finally:
            client_module.POSTHOG_API_KEY = original_key


# =============================================================================
# TESTS: REAL POSTHOG INTEGRATION
# =============================================================================


@pytest.mark.skipif(
    not os.getenv("POSTHOG_API_KEY"),
    reason="POSTHOG_API_KEY not set - skipping real PostHog tests"
)
class TestRealPostHogIntegration:
    """
    Integration tests that use real PostHog API.
    
    Run with:
        POSTHOG_API_KEY=your_key pytest tests/test_feature_flags.py::TestRealPostHogIntegration -v
    
    Test flag in PostHog:
        - Flag key: manor_python_module_test
        - Condition: distinct_id = "cicd"
    """

    def test_init_client_with_real_api(self, posthog_api_key):
        """Test initializing client with real API key."""
        from manor.feature_flags import init_client, shutdown_client
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = posthog_api_key
        
        try:
            client = init_client()
            assert client is not None
        finally:
            shutdown_client()
            client_module.POSTHOG_API_KEY = original_key

    def test_real_flag_returns_boolean(self, posthog_api_key):
        """Test real flag returns a boolean value."""
        from manor.feature_flags import is_enabled, init_client, shutdown_client
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = posthog_api_key
        
        try:
            init_client()
            
            # Flag should return a boolean (True or False)
            result = is_enabled("manor_python_module_test", user_id="cicd")
            assert isinstance(result, bool), f"Expected bool, got {type(result)}"
            print(f"\n  manor_python_module_test for 'cicd' = {result}")
        finally:
            shutdown_client()
            client_module.POSTHOG_API_KEY = original_key

    def test_real_flag_different_users(self, posthog_api_key):
        """Test real flag with different users."""
        from manor.feature_flags import is_enabled, init_client, shutdown_client
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = posthog_api_key
        
        try:
            init_client()
            
            # Test with different users - just verify it returns boolean
            for user_id in ["cicd", "random-user-12345", "test-user"]:
                result = is_enabled("manor_python_module_test", user_id=user_id)
                assert isinstance(result, bool), f"Expected bool for user {user_id}"
                print(f"\n  manor_python_module_test for '{user_id}' = {result}")
        finally:
            shutdown_client()
            client_module.POSTHOG_API_KEY = original_key

    def test_real_flag_with_feature_flag_checker(self, posthog_api_key):
        """Test real flag using FeatureFlagChecker class."""
        from manor.feature_flags import FeatureFlagChecker, init_client, shutdown_client
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = posthog_api_key
        
        try:
            init_client()
            
            # Using class method - verify it works without error
            result = FeatureFlagChecker.is_flag_enabled(
                "manor_python_module_test",
                user_id="cicd",
            )
            assert isinstance(result, bool)
            
            # Using instance method
            checker = FeatureFlagChecker("manor_python_module_test")
            result = checker.is_enabled(user_id="cicd")
            assert isinstance(result, bool)
            
            print(f"\n  FeatureFlagChecker result = {result}")
        finally:
            shutdown_client()
            client_module.POSTHOG_API_KEY = original_key

    def test_check_nonexistent_flag(self, posthog_api_key):
        """Test checking a flag that doesn't exist."""
        from manor.feature_flags import is_enabled, init_client, shutdown_client
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = posthog_api_key
        
        try:
            init_client()
            
            # Non-existent flag should return False
            result = is_enabled("nonexistent-flag-12345", user_id="test-user")
            assert result is False
        finally:
            shutdown_client()
            client_module.POSTHOG_API_KEY = original_key

    def test_get_flag_nonexistent(self, posthog_api_key):
        """Test getting a flag that doesn't exist."""
        from manor.feature_flags import get_flag, init_client, shutdown_client
        import manor.feature_flags.client as client_module
        
        original_key = client_module.POSTHOG_API_KEY
        client_module.POSTHOG_API_KEY = posthog_api_key
        
        try:
            init_client()
            
            # Non-existent flag should return default
            result = get_flag(
                "nonexistent-flag-12345",
                user_id="test-user",
                default="my-default",
            )
            assert result == "my-default"
        finally:
            shutdown_client()
            client_module.POSTHOG_API_KEY = original_key
