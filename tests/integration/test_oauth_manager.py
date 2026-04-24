"""Integration tests for OAuth2 flows (mocked).

Tests the OAuth2 token management integration including token initialization,
refresh flows, credential retrieval, and validation for both Google and
Outlook providers with mocked HTTP responses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.auth.oauth_manager import AuthenticationError, OAuthManager
from src.config.settings import settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def oauth_manager() -> OAuthManager:
    """Create a fresh OAuthManager with no pre-loaded tokens."""
    manager = OAuthManager()
    manager._token_cache = {}
    manager._refresh_locks = {}
    return manager


@pytest.fixture
def google_token_response() -> dict[str, Any]:
    """Mock Google token refresh response."""
    return {
        "access_token": "new-google-access-token",
        "refresh_token": "new-google-refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }


@pytest.fixture
def outlook_token_response() -> dict[str, Any]:
    """Mock Outlook token refresh response."""
    return {
        "access_token": "new-outlook-access-token",
        "refresh_token": "new-outlook-refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }


@pytest.fixture
def manager_with_google_token(oauth_manager: OAuthManager) -> OAuthManager:
    """OAuthManager pre-loaded with Google tokens."""
    oauth_manager._token_cache["google"] = {
        "access_token": "initial-google-token",
        "refresh_token": "initial-google-refresh-token",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    oauth_manager._refresh_locks["google"] = False
    return oauth_manager


@pytest.fixture
def manager_with_outlook_token(oauth_manager: OAuthManager) -> OAuthManager:
    """OAuthManager pre-loaded with Outlook tokens."""
    oauth_manager._token_cache["outlook"] = {
        "access_token": "initial-outlook-token",
        "refresh_token": "initial-outlook-refresh-token",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    oauth_manager._refresh_locks["outlook"] = False
    return oauth_manager


@pytest.fixture
def manager_with_expired_google_token(oauth_manager: OAuthManager) -> OAuthManager:
    """OAuthManager with an expired Google token."""
    oauth_manager._token_cache["google"] = {
        "access_token": "expired-google-token",
        "refresh_token": "google-refresh-token",
        "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    oauth_manager._refresh_locks["google"] = False
    return oauth_manager


@pytest.fixture
def manager_with_expired_outlook_token(oauth_manager: OAuthManager) -> OAuthManager:
    """OAuthManager with an expired Outlook token."""
    oauth_manager._token_cache["outlook"] = {
        "access_token": "expired-outlook-token",
        "refresh_token": "outlook-refresh-token",
        "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    oauth_manager._refresh_locks["outlook"] = False
    return oauth_manager


# ---------------------------------------------------------------------------
# Token Initialization Tests
# ---------------------------------------------------------------------------


class TestTokenInitialization:
    """Tests for initial token loading from settings."""

    def test_empty_cache_when_no_tokens(self, oauth_manager: OAuthManager) -> None:
        """Manager starts with empty cache when no tokens configured."""
        assert "google" not in oauth_manager._token_cache
        assert "outlook" not in oauth_manager._token_cache

    def test_set_google_token(self, oauth_manager: OAuthManager) -> None:
        """Setting a Google token stores it correctly."""
        oauth_manager.set_token("google", "access-123", "refresh-456", expires_in=7200)

        assert "google" in oauth_manager._token_cache
        token_info = oauth_manager._token_cache["google"]
        assert token_info["access_token"] == "access-123"
        assert token_info["refresh_token"] == "refresh-456"
        assert token_info["expires_at"] > datetime.now(timezone.utc)

    def test_set_outlook_token(self, oauth_manager: OAuthManager) -> None:
        """Setting an Outlook token stores it correctly."""
        oauth_manager.set_token("outlook", "access-789", expires_in=1800)

        assert "outlook" in oauth_manager._token_cache
        token_info = oauth_manager._token_cache["outlook"]
        assert token_info["access_token"] == "access-789"

    def test_set_token_preserves_existing_refresh_token(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Updating access token preserves existing refresh token."""
        oauth_manager.set_token("google", "old-access", "old-refresh")
        oauth_manager.set_token("google", "new-access")

        token_info = oauth_manager._token_cache["google"]
        assert token_info["access_token"] == "new-access"
        assert token_info["refresh_token"] == "old-refresh"

    def test_set_token_overwrites_refresh_token(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Explicitly passing a new refresh token overwrites the old one."""
        oauth_manager.set_token("google", "access", "old-refresh")
        oauth_manager.set_token("google", "access", "new-refresh")

        token_info = oauth_manager._token_cache["google"]
        assert token_info["refresh_token"] == "new-refresh"


# ---------------------------------------------------------------------------
# Get Credentials Tests
# ---------------------------------------------------------------------------


class TestGetCredentials:
    """Tests for the get_credentials() method."""

    @pytest.mark.asyncio
    async def test_returns_valid_token_without_refresh(
        self, manager_with_google_token: OAuthManager
    ) -> None:
        """Returns access token when it's still valid."""
        token = await manager_with_google_token.get_credentials("google")
        assert token == "initial-google-token"

    @pytest.mark.asyncio
    async def test_refreshes_expired_google_token(
        self,
        manager_with_expired_google_token: OAuthManager,
        google_token_response: dict[str, Any],
    ) -> None:
        """Automatically refreshes expired Google token."""
        mock_response = MagicMock()
        mock_response.json.return_value = google_token_response
        mock_response.raise_for_status = MagicMock()

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_client_id = "test-google-id"
            mock_settings.google_client_secret = "test-google-secret"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                token = await manager_with_expired_google_token.get_credentials("google")

                assert token == "new-google-access-token"
                assert (
                    manager_with_expired_google_token._token_cache["google"]["access_token"]
                    == "new-google-access-token"
                )

    @pytest.mark.asyncio
    async def test_refreshes_expired_outlook_token(
        self,
        manager_with_expired_outlook_token: OAuthManager,
        outlook_token_response: dict[str, Any],
    ) -> None:
        """Automatically refreshes expired Outlook token."""
        mock_response = MagicMock()
        mock_response.json.return_value = outlook_token_response
        mock_response.raise_for_status = MagicMock()

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.outlook_client_id = "test-outlook-id"
            mock_settings.outlook_client_secret = "test-outlook-secret"
            mock_settings.outlook_tenant_id = "common"
            mock_settings.outlook_scopes = ["Calendars.Read"]

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                token = await manager_with_expired_outlook_token.get_credentials("outlook")

                assert token == "new-outlook-access-token"

    @pytest.mark.asyncio
    async def test_raises_for_unconfigured_provider(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Raises AuthenticationError when provider has no credentials."""
        with pytest.raises(AuthenticationError) as exc_info:
            await oauth_manager.get_credentials("google")

        assert "No credentials configured" in str(exc_info.value)
        assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_raises_when_no_refresh_token_available(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Raises AuthenticationError when token is expired and no refresh token."""
        oauth_manager._token_cache["google"] = {
            "access_token": "expired-token",
            "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        oauth_manager._refresh_locks["google"] = False

        with pytest.raises(AuthenticationError) as exc_info:
            await oauth_manager.get_credentials("google")

        assert "no refresh token available" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_refreshes_token_nearing_expiry(
        self,
        manager_with_google_token: OAuthManager,
        google_token_response: dict[str, Any],
    ) -> None:
        """Refreshes token when it's within the refresh buffer (5 minutes)."""
        # Set token to expire in 2 minutes (within the 5-minute buffer)
        manager_with_google_token._token_cache["google"]["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(minutes=2)
        )

        mock_response = MagicMock()
        mock_response.json.return_value = google_token_response
        mock_response.raise_for_status = MagicMock()

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_client_id = "test-google-id"
            mock_settings.google_client_secret = "test-google-secret"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                token = await manager_with_google_token.get_credentials("google")

                assert token == "new-google-access-token"


# ---------------------------------------------------------------------------
# Token Refresh Tests
# ---------------------------------------------------------------------------


class TestTokenRefresh:
    """Tests for explicit token refresh flows."""

    @pytest.mark.asyncio
    async def test_refresh_google_token(
        self,
        oauth_manager: OAuthManager,
        google_token_response: dict[str, Any],
    ) -> None:
        """Successfully refreshes a Google token."""
        mock_response = MagicMock()
        mock_response.json.return_value = google_token_response
        mock_response.raise_for_status = MagicMock()

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_client_id = "test-google-id"
            mock_settings.google_client_secret = "test-google-secret"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                result = await oauth_manager.refresh_token("google", "refresh-token")

                assert result["access_token"] == "new-google-access-token"
                assert result["refresh_token"] == "new-google-refresh-token"
                assert "expires_at" in result

    @pytest.mark.asyncio
    async def test_refresh_outlook_token(
        self,
        oauth_manager: OAuthManager,
        outlook_token_response: dict[str, Any],
    ) -> None:
        """Successfully refreshes an Outlook token."""
        mock_response = MagicMock()
        mock_response.json.return_value = outlook_token_response
        mock_response.raise_for_status = MagicMock()

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.outlook_client_id = "test-outlook-id"
            mock_settings.outlook_client_secret = "test-outlook-secret"
            mock_settings.outlook_tenant_id = "common"
            mock_settings.outlook_scopes = ["Calendars.Read"]

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                result = await oauth_manager.refresh_token("outlook", "refresh-token")

                assert result["access_token"] == "new-outlook-access-token"

    @pytest.mark.asyncio
    async def test_refresh_google_token_missing_credentials(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Raises AuthenticationError when Google credentials not configured."""
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_client_id = ""
            mock_settings.google_client_secret = ""

            with pytest.raises(AuthenticationError) as exc_info:
                await oauth_manager.refresh_token("google", "refresh-token")

            assert "not configured" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_refresh_outlook_token_missing_credentials(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Raises AuthenticationError when Outlook credentials not configured."""
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.outlook_client_id = ""
            mock_settings.outlook_client_secret = ""
            mock_settings.outlook_tenant_id = "common"
            mock_settings.outlook_scopes = ["Calendars.Read"]

            with pytest.raises(AuthenticationError) as exc_info:
                await oauth_manager.refresh_token("outlook", "refresh-token")

            assert "not configured" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_refresh_unsupported_provider(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Raises ValueError for unsupported provider."""
        with pytest.raises(ValueError) as exc_info:
            await oauth_manager.refresh_token("yahoo", "refresh-token")

        assert "Unsupported provider" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_refresh_google_http_error(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Handles HTTP error during Google token refresh."""
        mock_response = MagicMock()
        mock_response.text = '{"error": "invalid_grant"}'

        http_error = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=mock_response
        )

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_client_id = "test-google-id"
            mock_settings.google_client_secret = "test-google-secret"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.side_effect = http_error
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                with pytest.raises(AuthenticationError) as exc_info:
                    await oauth_manager.refresh_token("google", "bad-refresh-token")

                assert "invalid_grant" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_refresh_outlook_http_error(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Handles HTTP error during Outlook token refresh."""
        mock_response = MagicMock()
        mock_response.text = '{"error": "invalid_grant"}'

        http_error = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=mock_response
        )

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.outlook_client_id = "test-outlook-id"
            mock_settings.outlook_client_secret = "test-outlook-secret"
            mock_settings.outlook_tenant_id = "common"
            mock_settings.outlook_scopes = ["Calendars.Read"]

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.side_effect = http_error
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                with pytest.raises(AuthenticationError) as exc_info:
                    await oauth_manager.refresh_token("outlook", "bad-refresh-token")

                assert "invalid_grant" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_refresh_google_request_error(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Handles network error during Google token refresh."""
        request_error = httpx.RequestError("Connection refused")

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_client_id = "test-google-id"
            mock_settings.google_client_secret = "test-google-secret"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.side_effect = request_error
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                with pytest.raises(AuthenticationError) as exc_info:
                    await oauth_manager.refresh_token("google", "refresh-token")

                assert "request failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_refresh_preserves_existing_refresh_token(
        self,
        oauth_manager: OAuthManager,
        google_token_response: dict[str, Any],
    ) -> None:
        """Preserves existing refresh token if response doesn't include one."""
        response_without_refresh = dict(google_token_response)
        del response_without_refresh["refresh_token"]

        mock_response = MagicMock()
        mock_response.json.return_value = response_without_refresh
        mock_response.raise_for_status = MagicMock()

        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_client_id = "test-google-id"
            mock_settings.google_client_secret = "test-google-secret"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client_cls.return_value.__aenter__.return_value = mock_client

                await oauth_manager.refresh_token("google", "original-refresh")

                token_info = oauth_manager._token_cache["google"]
                assert token_info["refresh_token"] == "original-refresh"

    @pytest.mark.asyncio
    async def test_refresh_lock_prevents_concurrent_refreshes(
        self,
        manager_with_expired_google_token: OAuthManager,
        google_token_response: dict[str, Any],
    ) -> None:
        """Lock prevents concurrent refresh attempts for same provider."""
        mock_response = MagicMock()
        mock_response.json.return_value = google_token_response
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            # Set the lock to True to simulate concurrent refresh
            manager_with_expired_google_token._refresh_locks["google"] = True

            # Should return without attempting refresh
            await manager_with_expired_google_token._refresh_token(
                "google", "refresh-token"
            )

            # Token should still be the old one (no refresh occurred)
            assert (
                manager_with_expired_google_token._token_cache["google"]["access_token"]
                == "expired-google-token"
            )


# ---------------------------------------------------------------------------
# Token Validation Tests
# ---------------------------------------------------------------------------


class TestTokenValidation:
    """Tests for token validation with providers."""

    @pytest.mark.asyncio
    async def test_validate_google_token_valid(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Valid Google token returns True."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            result = await oauth_manager.validate_token(
                "google", "valid-access-token"
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_validate_google_token_invalid(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Invalid Google token returns False."""
        mock_response = MagicMock()
        mock_response.status_code = 400

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            result = await oauth_manager.validate_token(
                "google", "invalid-access-token"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_validate_outlook_token_valid(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Valid Outlook token returns True."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            result = await oauth_manager.validate_token(
                "outlook", "valid-access-token"
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_validate_outlook_token_invalid(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Invalid Outlook token returns False."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            result = await oauth_manager.validate_token(
                "outlook", "invalid-access-token"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_validate_unknown_provider(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Unknown provider returns False."""
        result = await oauth_manager.validate_token("yahoo", "some-token")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_google_token_network_error(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Network error during validation returns False."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.RequestError("Connection error")
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            result = await oauth_manager.validate_token(
                "google", "access-token"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_validate_outlook_token_network_error(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Network error during Outlook validation returns False."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.RequestError("Connection error")
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            result = await oauth_manager.validate_token(
                "outlook", "access-token"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_validate_google_token_sends_correct_url(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Google validation calls the correct endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            await oauth_manager.validate_token("google", "test-token")

            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "oauth2.googleapis.com/tokeninfo" in str(call_args)

    @pytest.mark.asyncio
    async def test_validate_outlook_token_sends_correct_url(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Outlook validation calls the correct Graph endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            await oauth_manager.validate_token("outlook", "test-token")

            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            assert "graph.microsoft.com/v1.0/me" in str(call_args)

    @pytest.mark.asyncio
    async def test_validate_outlook_token_sends_auth_header(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Outlook validation includes Authorization header."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            await oauth_manager.validate_token("outlook", "my-token")

            call_args = mock_client.get.call_args
            headers = call_args.kwargs.get("headers", {})
            assert headers.get("Authorization") == "Bearer my-token"


# ---------------------------------------------------------------------------
# Token Info and Expiry Tests
# ---------------------------------------------------------------------------


class TestTokenInfoAndExpiry:
    """Tests for token metadata and expiry checking."""

    def test_is_token_expired_when_configured_and_valid(
        self, manager_with_google_token: OAuthManager
    ) -> None:
        """Returns False when token is still valid."""
        assert not manager_with_google_token.is_token_expired("google")

    def test_is_token_expired_when_expired(
        self, manager_with_expired_google_token: OAuthManager
    ) -> None:
        """Returns True when token has expired."""
        assert manager_with_expired_google_token.is_token_expired("google")

    def test_is_token_expired_when_unconfigured(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Returns True when provider has no tokens."""
        assert oauth_manager.is_token_expired("google")

    def test_get_token_info_returns_metadata(
        self, manager_with_google_token: OAuthManager
    ) -> None:
        """Returns token metadata without exposing the access token."""
        info = manager_with_google_token.get_token_info("google")

        assert info is not None
        assert "has_refresh_token" in info
        assert "expires_at" in info
        assert "is_expired" in info
        assert info["has_refresh_token"] is True
        assert info["is_expired"] is False

    def test_get_token_info_returns_none_for_unconfigured(
        self, oauth_manager: OAuthManager
    ) -> None:
        """Returns None when provider has no tokens."""
        info = oauth_manager.get_token_info("google")
        assert info is None

    def test_get_token_info_no_refresh_token(
        self, oauth_manager: OAuthManager
    ) -> None:
        """has_refresh_token is False when no refresh token present."""
        oauth_manager._token_cache["google"] = {
            "access_token": "token",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }

        info = oauth_manager.get_token_info("google")
        assert info is not None
        assert info["has_refresh_token"] is False


# ---------------------------------------------------------------------------
# AuthenticationError Tests
# ---------------------------------------------------------------------------


class TestAuthenticationError:
    """Tests for the AuthenticationError exception."""

    def test_error_with_provider(self) -> None:
        """Error stores provider context."""
        err = AuthenticationError("test error", provider="google")
        assert str(err) == "test error"
        assert err.provider == "google"

    def test_error_without_provider(self) -> None:
        """Error works without provider context."""
        err = AuthenticationError("test error")
        assert str(err) == "test error"
        assert err.provider is None

    def test_error_is_exception(self) -> None:
        """AuthenticationError is a proper exception."""
        err = AuthenticationError("test")
        assert isinstance(err, Exception)
