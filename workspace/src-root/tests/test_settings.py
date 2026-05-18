"""Tests for configuration settings."""
import os
import pytest
from unittest.mock import patch

from src.config.settings import Settings


class TestSettings:
    def test_default_values(self):
        settings = Settings()
        assert settings.server_host == "0.0.0.0"
        assert settings.server_port == 8000
        assert settings.debug is False
        assert settings.google_client_id == ""
        assert settings.google_client_secret == ""
        assert settings.default_provider == "google"
        assert settings.outlook_tenant_id == "common"

    def test_custom_values(self):
        settings = Settings(
            server_host="127.0.0.1",
            server_port=9000,
            debug=True,
            default_provider="outlook",
        )
        assert settings.server_host == "127.0.0.1"
        assert settings.server_port == 9000
        assert settings.debug is True
        assert settings.default_provider == "outlook"

    def test_google_oauth_fields(self):
        settings = Settings(
            google_client_id="g_client_id",
            google_client_secret="g_client_secret",
            google_redirect_uri="http://example.com/callback",
            google_access_token="g_access_token",
            google_refresh_token="g_refresh_token",
        )
        assert settings.google_client_id == "g_client_id"
        assert settings.google_client_secret == "g_client_secret"
        assert settings.google_redirect_uri == "http://example.com/callback"
        assert settings.google_access_token == "g_access_token"
        assert settings.google_refresh_token == "g_refresh_token"

    def test_outlook_oauth_fields(self):
        settings = Settings(
            outlook_client_id="o_client_id",
            outlook_client_secret="o_client_secret",
            outlook_redirect_uri="http://example.com/outlook/callback",
            outlook_access_token="o_access_token",
            outlook_refresh_token="o_refresh_token",
            outlook_tenant_id="tenant123",
        )
        assert settings.outlook_client_id == "o_client_id"
        assert settings.outlook_client_secret == "o_client_secret"
        assert settings.outlook_redirect_uri == "http://example.com/outlook/callback"
        assert settings.outlook_access_token == "o_access_token"
        assert settings.outlook_refresh_token == "o_refresh_token"
        assert settings.outlook_tenant_id == "tenant123"

    def test_rate_limit_defaults(self):
        settings = Settings()
        assert settings.rate_limit_google_capacity == 10000
        assert settings.rate_limit_google_refill_rate == 100.0
        assert settings.rate_limit_outlook_capacity == 10000
        assert settings.rate_limit_default_capacity == 1000
        assert settings.rate_limit_default_refill_rate == 10.0
        assert settings.rate_limit_max_retries == 3
        assert settings.rate_limit_backoff_base == 1.0

    def test_rate_limit_custom(self):
        settings = Settings(
            rate_limit_google_capacity=5000,
            rate_limit_google_refill_rate=50.0,
            rate_limit_outlook_capacity=5000,
            rate_limit_outlook_refill_rate=8.33,
            rate_limit_default_capacity=500,
            rate_limit_default_refill_rate=5.0,
            rate_limit_max_retries=5,
            rate_limit_backoff_base=2.0,
        )
        assert settings.rate_limit_google_capacity == 5000
        assert settings.rate_limit_google_refill_rate == 50.0
        assert settings.rate_limit_outlook_capacity == 5000
        assert settings.rate_limit_outlook_refill_rate == 8.33
        assert settings.rate_limit_default_capacity == 500
        assert settings.rate_limit_default_refill_rate == 5.0
        assert settings.rate_limit_max_retries == 5
        assert settings.rate_limit_backoff_base == 2.0

    @patch.dict(os.environ, {
        "SERVER_HOST": "127.0.0.1",
        "SERVER_PORT": "9000",
        "DEBUG": "true",
        "GOOGLE_CLIENT_ID": "env_google_id",
        "GOOGLE_CLIENT_SECRET": "env_google_secret",
        "DEFAULT_PROVIDER": "outlook",
        "OUTLOOK_TENANT_ID": "env_tenant",
    }, clear=False)
    def test_environment_variable_loading(self):
        settings = Settings()
        assert settings.server_host == "127.0.0.1"
        assert settings.server_port == 9000
        assert settings.debug is True
        assert settings.google_client_id == "env_google_id"
        assert settings.google_client_secret == "env_google_secret"
        assert settings.default_provider == "outlook"
        assert settings.outlook_tenant_id == "env_tenant"
