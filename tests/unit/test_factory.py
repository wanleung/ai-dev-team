"""Unit tests for the provider factory function.

Tests cover:
- create_provider() with google, outlook, default, and unknown providers
- ProviderConfig construction from settings
- Error handling for unsupported providers
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("kiota_abstractions", reason="outlook provider requires kiota_abstractions")
pytest.importorskip("msgraph", reason="outlook provider requires msgraph-sdk")

from src.calendar_provider.factory import create_provider
from src.calendar_provider.google_provider import GoogleCalendarProvider
from src.calendar_provider.outlook_provider import OutlookCalendarProvider
from src.models.calendar import ProviderConfig


class TestCreateProvider:
    """Tests for the create_provider factory function."""

    @patch("src.calendar_provider.factory.settings")
    def test_creates_google_provider(self, mock_settings: MagicMock) -> None:
        """create_provider('google') returns GoogleCalendarProvider."""
        mock_settings.default_provider = "outlook"
        mock_settings.google_client_id = "g_id"
        mock_settings.google_client_secret = "g_secret"
        mock_settings.google_redirect_uri = "http://localhost/g_callback"
        mock_settings.google_access_token = "g_token"
        mock_settings.google_refresh_token = "g_refresh"
        mock_settings.google_scopes = ["https://www.googleapis.com/auth/calendar"]

        provider = create_provider("google")

        assert isinstance(provider, GoogleCalendarProvider)
        assert provider.config.provider == "google"
        assert provider.config.client_id == "g_id"

    @patch("src.calendar_provider.factory.settings")
    def test_creates_outlook_provider(self, mock_settings: MagicMock) -> None:
        """create_provider('outlook') returns OutlookCalendarProvider."""
        mock_settings.default_provider = "google"
        mock_settings.outlook_client_id = "o_id"
        mock_settings.outlook_client_secret = "o_secret"
        mock_settings.outlook_redirect_uri = "http://localhost/o_callback"
        mock_settings.outlook_access_token = "o_token"
        mock_settings.outlook_refresh_token = "o_refresh"
        mock_settings.outlook_scopes = ["Calendars.Read"]

        provider = create_provider("outlook")

        assert isinstance(provider, OutlookCalendarProvider)
        assert provider.config.provider == "outlook"
        assert provider.config.client_id == "o_id"

    @patch("src.calendar_provider.factory.settings")
    def test_uses_default_provider_when_none_specified(self, mock_settings: MagicMock) -> None:
        """create_provider(None) uses settings.default_provider."""
        mock_settings.default_provider = "google"
        mock_settings.google_client_id = "g_id"
        mock_settings.google_client_secret = "g_secret"
        mock_settings.google_redirect_uri = "http://localhost/g_callback"
        mock_settings.google_access_token = "g_token"
        mock_settings.google_refresh_token = "g_refresh"
        mock_settings.google_scopes = ["calendar"]

        provider = create_provider(None)

        assert isinstance(provider, GoogleCalendarProvider)

    @patch("src.calendar_provider.factory.settings")
    def test_default_provider_outlook(self, mock_settings: MagicMock) -> None:
        """create_provider(None) with default_provider='outlook' returns OutlookCalendarProvider."""
        mock_settings.default_provider = "outlook"
        mock_settings.outlook_client_id = "o_id"
        mock_settings.outlook_client_secret = "o_secret"
        mock_settings.outlook_redirect_uri = "http://localhost/o_callback"
        mock_settings.outlook_access_token = "o_token"
        mock_settings.outlook_refresh_token = "o_refresh"
        mock_settings.outlook_scopes = ["Calendars.Read"]

        provider = create_provider(None)

        assert isinstance(provider, OutlookCalendarProvider)

    @patch("src.calendar_provider.factory.settings")
    def test_case_insensitive_provider_name(self, mock_settings: MagicMock) -> None:
        """Provider name is case-insensitive."""
        mock_settings.default_provider = "google"
        mock_settings.google_client_id = "g_id"
        mock_settings.google_client_secret = "g_secret"
        mock_settings.google_redirect_uri = "http://localhost/g_callback"
        mock_settings.google_access_token = "g_token"
        mock_settings.google_refresh_token = "g_refresh"
        mock_settings.google_scopes = ["calendar"]

        provider = create_provider("GOOGLE")

        assert isinstance(provider, GoogleCalendarProvider)

    @patch("src.calendar_provider.factory.settings")
    def test_raises_for_unknown_provider(self, mock_settings: MagicMock) -> None:
        """create_provider('yahoo') raises ValueError."""
        mock_settings.default_provider = "google"

        with pytest.raises(ValueError) as exc_info:
            create_provider("yahoo")

        assert "Unknown provider" in str(exc_info.value)
        assert "yahoo" in str(exc_info.value)

    @patch("src.calendar_provider.factory.settings")
    def test_google_config_has_correct_scopes(self, mock_settings: MagicMock) -> None:
        """Google provider config receives scopes from settings."""
        mock_settings.default_provider = "outlook"
        mock_settings.google_client_id = "g_id"
        mock_settings.google_client_secret = "g_secret"
        mock_settings.google_redirect_uri = "http://localhost/g_callback"
        mock_settings.google_access_token = "g_token"
        mock_settings.google_refresh_token = "g_refresh"
        mock_settings.google_scopes = ["scope1", "scope2"]

        provider = create_provider("google")

        assert provider.config.scopes == ["scope1", "scope2"]

    @patch("src.calendar_provider.factory.settings")
    def test_outlook_config_has_correct_scopes(self, mock_settings: MagicMock) -> None:
        """Outlook provider config receives scopes from settings."""
        mock_settings.default_provider = "google"
        mock_settings.outlook_client_id = "o_id"
        mock_settings.outlook_client_secret = "o_secret"
        mock_settings.outlook_redirect_uri = "http://localhost/o_callback"
        mock_settings.outlook_access_token = "o_token"
        mock_settings.outlook_refresh_token = "o_refresh"
        mock_settings.outlook_scopes = ["Calendars.Read", "Calendars.ReadWrite"]

        provider = create_provider("outlook")

        assert provider.config.scopes == ["Calendars.Read", "Calendars.ReadWrite"]

    @patch("src.calendar_provider.factory.settings")
    def test_google_config_redirect_uri(self, mock_settings: MagicMock) -> None:
        """Google provider config receives redirect_uri from settings."""
        mock_settings.default_provider = "outlook"
        mock_settings.google_client_id = "g_id"
        mock_settings.google_client_secret = "g_secret"
        mock_settings.google_redirect_uri = "http://example.com/callback"
        mock_settings.google_access_token = "g_token"
        mock_settings.google_refresh_token = "g_refresh"
        mock_settings.google_scopes = ["calendar"]

        provider = create_provider("google")

        assert provider.config.redirect_uri == "http://example.com/callback"

    @patch("src.calendar_provider.factory.settings")
    def test_outlook_config_redirect_uri(self, mock_settings: MagicMock) -> None:
        """Outlook provider config receives redirect_uri from settings."""
        mock_settings.default_provider = "google"
        mock_settings.outlook_client_id = "o_id"
        mock_settings.outlook_client_secret = "o_secret"
        mock_settings.outlook_redirect_uri = "http://example.com/outlook/callback"
        mock_settings.outlook_access_token = "o_token"
        mock_settings.outlook_refresh_token = "o_refresh"
        mock_settings.outlook_scopes = ["Calendars.Read"]

        provider = create_provider("outlook")

        assert provider.config.redirect_uri == "http://example.com/outlook/callback"

    @patch("src.calendar_provider.factory.settings")
    def test_google_config_tokens(self, mock_settings: MagicMock) -> None:
        """Google provider config receives tokens from settings."""
        mock_settings.default_provider = "outlook"
        mock_settings.google_client_id = "g_id"
        mock_settings.google_client_secret = "g_secret"
        mock_settings.google_redirect_uri = "http://localhost/g_callback"
        mock_settings.google_access_token = "my_access"
        mock_settings.google_refresh_token = "my_refresh"
        mock_settings.google_scopes = ["calendar"]

        provider = create_provider("google")

        assert provider.config.access_token == "my_access"
        assert provider.config.refresh_token == "my_refresh"

    @patch("src.calendar_provider.factory.settings")
    def test_outlook_config_tokens(self, mock_settings: MagicMock) -> None:
        """Outlook provider config receives tokens from settings."""
        mock_settings.default_provider = "google"
        mock_settings.outlook_client_id = "o_id"
        mock_settings.outlook_client_secret = "o_secret"
        mock_settings.outlook_redirect_uri = "http://localhost/o_callback"
        mock_settings.outlook_access_token = "my_o_access"
        mock_settings.outlook_refresh_token = "my_o_refresh"
        mock_settings.outlook_scopes = ["Calendars.Read"]

        provider = create_provider("outlook")

        assert provider.config.access_token == "my_o_access"
        assert provider.config.refresh_token == "my_o_refresh"
