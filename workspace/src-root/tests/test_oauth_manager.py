"""Tests for OAuth manager."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock

from src.auth.oauth_manager import OAuthManager, AuthenticationError


class TestOAuthManagerInit:
    def test_empty_cache_on_init(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            assert "google" not in manager._token_cache
            assert "outlook" not in manager._token_cache

    def test_initializes_google_token_from_settings(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = "test_token"
            mock_settings.google_refresh_token = "test_refresh"
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            assert "google" in manager._token_cache
            assert manager._token_cache["google"]["access_token"] == "test_token"
            assert manager._token_cache["google"]["refresh_token"] == "test_refresh"

    def test_initializes_outlook_token_from_settings(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = "outlook_token"
            mock_settings.outlook_refresh_token = "outlook_refresh"
            manager = OAuthManager()
            assert "outlook" in manager._token_cache
            assert manager._token_cache["outlook"]["access_token"] == "outlook_token"


class TestSetToken:
    def test_set_google_token(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "new_access", "new_refresh", expires_in=7200)
            assert manager._token_cache["google"]["access_token"] == "new_access"
            assert manager._token_cache["google"]["refresh_token"] == "new_refresh"

    def test_set_outlook_token(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("outlook", "outlook_access", "outlook_refresh")
            assert manager._token_cache["outlook"]["access_token"] == "outlook_access"

    def test_set_token_preserves_existing_refresh(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "new_access", "original_refresh")
            manager.set_token("google", "another_access")
            assert manager._token_cache["google"]["access_token"] == "another_access"
            assert manager._token_cache["google"]["refresh_token"] == "original_refresh"

    def test_set_token_overwrites_refresh_when_provided(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "access1", "refresh1")
            manager.set_token("google", "access2", "refresh2")
            assert manager._token_cache["google"]["refresh_token"] == "refresh2"


class TestGetCredentials:
    @pytest.mark.asyncio
    async def test_returns_valid_token(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "valid_token", expires_in=3600)
            token = await manager.get_credentials("google")
            assert token == "valid_token"

    @pytest.mark.asyncio
    async def test_raises_for_unconfigured_provider(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            with pytest.raises(AuthenticationError) as exc_info:
                await manager.get_credentials("google")
            assert "No credentials configured" in str(exc_info.value)
            assert exc_info.value.provider == "google"

    @pytest.mark.asyncio
    async def test_raises_when_expired_and_no_refresh_token(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "expired_token", expires_in=0)
            manager._token_cache["google"]["expires_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
            with pytest.raises(AuthenticationError) as exc_info:
                await manager.get_credentials("google")
            assert "no refresh token available" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_auto_refreshes_expired_google_token(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.google_client_id = "client_id"
            mock_settings.google_client_secret = "client_secret"
            manager = OAuthManager()
            manager.set_token("google", "old_token", "refresh_token", expires_in=0)
            manager._token_cache["google"]["expires_at"] = datetime.now(timezone.utc) - timedelta(hours=1)

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                token = await manager.get_credentials("google")
                assert token == "new_token"

    @pytest.mark.asyncio
    async def test_auto_refreshes_expired_outlook_token(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.outlook_client_id = "client_id"
            mock_settings.outlook_client_secret = "client_secret"
            mock_settings.outlook_tenant_id = "common"
            mock_settings.outlook_scopes = ["Calendars.Read"]
            manager = OAuthManager()
            manager.set_token("outlook", "old_token", "refresh_token", expires_in=0)
            manager._token_cache["outlook"]["expires_at"] = datetime.now(timezone.utc) - timedelta(hours=1)

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "new_outlook_token",
                "refresh_token": "new_outlook_refresh",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                token = await manager.get_credentials("outlook")
                assert token == "new_outlook_token"


class TestRefreshToken:
    @pytest.mark.asyncio
    async def test_refresh_google_token_success(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.google_client_id = "client_id"
            mock_settings.google_client_secret = "client_secret"
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "new_google_token",
                "refresh_token": "new_google_refresh",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await manager.refresh_token("google", "old_refresh")
                assert result["access_token"] == "new_google_token"
                assert result["refresh_token"] == "new_google_refresh"

    @pytest.mark.asyncio
    async def test_refresh_outlook_token_success(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.outlook_client_id = "client_id"
            mock_settings.outlook_client_secret = "client_secret"
            mock_settings.outlook_tenant_id = "common"
            mock_settings.outlook_scopes = ["Calendars.Read"]
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "new_outlook_token",
                "refresh_token": "new_outlook_refresh",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await manager.refresh_token("outlook", "old_refresh")
                assert result["access_token"] == "new_outlook_token"

    @pytest.mark.asyncio
    async def test_refresh_google_token_missing_credentials(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.google_client_id = ""
            mock_settings.google_client_secret = ""
            manager = OAuthManager()
            with pytest.raises(AuthenticationError) as exc_info:
                await manager.refresh_token("google", "refresh_token")
            assert "not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_refresh_outlook_token_missing_credentials(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.outlook_client_id = ""
            mock_settings.outlook_client_secret = ""
            manager = OAuthManager()
            with pytest.raises(AuthenticationError) as exc_info:
                await manager.refresh_token("outlook", "refresh_token")
            assert "not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_refresh_unsupported_provider(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            with pytest.raises(ValueError) as exc_info:
                await manager.refresh_token("unknown", "refresh_token")
            assert "Unsupported provider" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_refresh_google_token_http_error(self):
        import httpx
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.google_client_id = "client_id"
            mock_settings.google_client_secret = "client_secret"
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.text = "invalid_grant"
            http_error = httpx.HTTPStatusError(
                "Bad Request", request=MagicMock(), response=mock_response
            )

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.side_effect = http_error
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                with pytest.raises(AuthenticationError) as exc_info:
                    await manager.refresh_token("google", "refresh_token")
                assert "google" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_refresh_google_token_network_error(self):
        import httpx
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.google_client_id = "client_id"
            mock_settings.google_client_secret = "client_secret"
            manager = OAuthManager()

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.side_effect = httpx.RequestError("Network error")
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                with pytest.raises(AuthenticationError) as exc_info:
                    await manager.refresh_token("google", "refresh_token")
                assert "google" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_refresh_preserves_refresh_token(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.google_client_id = "client_id"
            mock_settings.google_client_secret = "client_secret"
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "new_token",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                await manager.refresh_token("google", "original_refresh")
                assert manager._token_cache["google"]["refresh_token"] == "original_refresh"

    @pytest.mark.asyncio
    async def test_concurrent_refresh_lock_prevention(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            mock_settings.google_client_id = "client_id"
            mock_settings.google_client_secret = "client_secret"
            manager = OAuthManager()
            manager._refresh_locks["google"] = True

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "access_token": "new_token",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                await manager._refresh_token("google", "refresh_token")
                mock_instance.post.assert_not_called()


class TestValidateToken:
    @pytest.mark.asyncio
    async def test_validate_google_token_valid(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.status_code = 200

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await manager.validate_token("google", "valid_token")
                assert result is True

    @pytest.mark.asyncio
    async def test_validate_google_token_invalid(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.status_code = 400

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await manager.validate_token("google", "invalid_token")
                assert result is False

    @pytest.mark.asyncio
    async def test_validate_outlook_token_valid(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.status_code = 200

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await manager.validate_token("outlook", "valid_token")
                assert result is True

    @pytest.mark.asyncio
    async def test_validate_outlook_token_invalid(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.status_code = 401

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await manager.validate_token("outlook", "invalid_token")
                assert result is False

    @pytest.mark.asyncio
    async def test_validate_unknown_provider(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            result = await manager.validate_token("unknown", "token")
            assert result is False

    @pytest.mark.asyncio
    async def test_validate_google_token_uses_correct_endpoint(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.status_code = 200

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                await manager.validate_token("google", "test_token")
                mock_instance.get.assert_called_once()
                call_args = mock_instance.get.call_args
                assert "oauth2.googleapis.com/tokeninfo" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_validate_outlook_token_uses_correct_endpoint(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.status_code = 200

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                await manager.validate_token("outlook", "test_token")
                mock_instance.get.assert_called_once()
                call_args = mock_instance.get.call_args
                assert "graph.microsoft.com/v1.0/me" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_validate_outlook_token_sends_auth_header(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()

            mock_response = MagicMock()
            mock_response.status_code = 200

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.return_value = mock_response
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                await manager.validate_token("outlook", "test_token")
                call_kwargs = mock_instance.get.call_args[1]
                assert "headers" in call_kwargs
                assert call_kwargs["headers"]["Authorization"] == "Bearer test_token"

    @pytest.mark.asyncio
    async def test_validate_token_network_error(self):
        import httpx
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.get.side_effect = httpx.RequestError("Network error")
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await manager.validate_token("google", "token")
                assert result is False


class TestTokenInfo:
    def test_is_token_expired_true(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "token", expires_in=0)
            manager._token_cache["google"]["expires_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
            assert manager.is_token_expired("google") is True

    def test_is_token_expired_false(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "token", expires_in=3600)
            assert manager.is_token_expired("google") is False

    def test_is_token_expired_unconfigured(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            assert manager.is_token_expired("google") is True

    def test_get_token_info_returns_metadata(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "token", "refresh_token", expires_in=3600)
            info = manager.get_token_info("google")
            assert info is not None
            assert info["has_refresh_token"] is True
            assert "expires_at" in info
            assert "is_expired" in info

    def test_get_token_info_does_not_expose_access_token(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            manager.set_token("google", "secret_token", expires_in=3600)
            info = manager.get_token_info("google")
            assert info is not None
            assert "access_token" not in info

    def test_get_token_info_returns_none_for_unconfigured(self):
        with patch("src.auth.oauth_manager.settings") as mock_settings:
            mock_settings.google_access_token = None
            mock_settings.outlook_access_token = None
            manager = OAuthManager()
            info = manager.get_token_info("google")
            assert info is None


class TestAuthenticationError:
    def test_error_with_provider(self):
        error = AuthenticationError("Test error", provider="google")
        assert str(error) == "Test error"
        assert error.provider == "google"

    def test_error_without_provider(self):
        error = AuthenticationError("Test error")
        assert str(error) == "Test error"
        assert error.provider is None

    def test_inherits_from_exception(self):
        error = AuthenticationError("Test error")
        assert isinstance(error, Exception)
