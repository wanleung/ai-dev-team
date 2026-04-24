"""Tests for OAuth2 token lifecycle management."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from imap.oauth2_manager import (
    OAuth2Manager,
    OAuth2TokenInfo,
    OAuth2TokenError,
    OAuth2ProviderError,
    PROVIDER_CONFIGS,
)


class TestOAuth2TokenInfo:
    """Tests for OAuth2TokenInfo data class."""

    def test_init_stores_values(self):
        token = OAuth2TokenInfo(
            access_token="access-123",
            refresh_token="refresh-456",
            expires_at=time.time() + 3600,
            token_type="Bearer",
            scope="mail.read",
        )
        assert token.access_token == "access-123"
        assert token.refresh_token == "refresh-456"
        assert token.token_type == "Bearer"
        assert token.scope == "mail.read"

    def test_is_expired_returns_false_for_future_token(self):
        token = OAuth2TokenInfo(
            access_token="access",
            refresh_token="refresh",
            expires_at=time.time() + 3600,
        )
        assert token.is_expired is False

    def test_is_expired_returns_true_for_past_token(self):
        token = OAuth2TokenInfo(
            access_token="access",
            refresh_token="refresh",
            expires_at=time.time() - 100,
        )
        assert token.is_expired is True

    def test_is_expired_returns_true_within_refresh_buffer(self):
        buffer = OAuth2TokenInfo.REFRESH_BUFFER_SECONDS
        token = OAuth2TokenInfo(
            access_token="access",
            refresh_token="refresh",
            expires_at=time.time() + buffer - 10,
        )
        assert token.is_expired is True

    def test_is_expired_returns_false_just_outside_refresh_buffer(self):
        buffer = OAuth2TokenInfo.REFRESH_BUFFER_SECONDS
        token = OAuth2TokenInfo(
            access_token="access",
            refresh_token="refresh",
            expires_at=time.time() + buffer + 10,
        )
        assert token.is_expired is False

    def test_from_token_response_creates_instance(self):
        response = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "mail.read",
        }
        token = OAuth2TokenInfo.from_token_response(response, "old-refresh")
        assert token.access_token == "new-access"
        assert token.refresh_token == "new-refresh"
        assert token.token_type == "Bearer"
        assert token.scope == "mail.read"
        assert token.expires_at > time.time()

    def test_from_token_response_keeps_old_refresh_if_not_in_response(self):
        response = {
            "access_token": "new-access",
            "expires_in": 3600,
        }
        token = OAuth2TokenInfo.from_token_response(response, "old-refresh")
        assert token.refresh_token == "old-refresh"

    def test_from_token_response_default_values(self):
        response = {"access_token": "tok"}
        token = OAuth2TokenInfo.from_token_response(response, "refresh")
        assert token.token_type == "Bearer"
        assert token.scope == ""

    def test_from_token_response_default_expires_in(self):
        response = {"access_token": "tok"}
        token = OAuth2TokenInfo.from_token_response(response, "refresh")
        assert token.expires_at > time.time() + 3500


class TestOAuth2ManagerProviderConfig:
    """Tests for OAuth2Manager.get_provider_config."""

    def test_gmail_config(self):
        config = OAuth2Manager.get_provider_config("gmail")
        assert config["token_url"] == "https://oauth2.googleapis.com/token"
        assert "https://mail.google.com/" in config["scopes"]

    def test_outlook_config(self):
        config = OAuth2Manager.get_provider_config("outlook")
        assert "login.microsoftonline.com" in config["token_url"]
        assert "offline_access" in config["scopes"]

    def test_yahoo_config(self):
        config = OAuth2Manager.get_provider_config("yahoo")
        assert "api.login.yahoo.com" in config["token_url"]
        assert "mail-r" in config["scopes"]

    def test_unknown_provider_raises_error(self):
        with pytest.raises(OAuth2TokenError, match="Unknown OAuth2 provider"):
            OAuth2Manager.get_provider_config("unknown")

    def test_provider_case_insensitive(self):
        config = OAuth2Manager.get_provider_config("GMAIL")
        assert config["token_url"] == "https://oauth2.googleapis.com/token"


class TestOAuth2ManagerInit:
    """Tests for OAuth2Manager initialization."""

    def test_init_with_encryption_manager(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        assert manager.encryption_manager == encryption_manager
        assert manager.default_timeout == 30.0
        assert manager._tokens == {}
        assert manager._locks == {}

    def test_init_without_encryption_manager(self):
        with patch("imap.oauth2_manager.get_encryption_manager") as mock_get:
            mock_enc = MagicMock()
            mock_get.return_value = mock_enc
            manager = OAuth2Manager()
            assert manager.encryption_manager == mock_enc

    def test_init_custom_timeout(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager, default_timeout=60.0)
        assert manager.default_timeout == 60.0


class TestOAuth2ManagerGetAccessToken:
    """Tests for OAuth2Manager.get_access_token."""

    @pytest.mark.asyncio
    async def test_returns_cached_token_if_valid(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        future_expiry = time.time() + 3600
        manager._tokens[1] = OAuth2TokenInfo(
            access_token="cached-token",
            refresh_token="refresh",
            expires_at=future_expiry,
        )

        token = await manager.get_access_token(1)
        assert token == "cached-token"

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        past_expiry = time.time() - 100
        manager._tokens[1] = OAuth2TokenInfo(
            access_token="expired-token",
            refresh_token="refresh",
            expires_at=past_expiry,
        )

        new_token = OAuth2TokenInfo(
            access_token="fresh-token",
            refresh_token="refresh",
            expires_at=time.time() + 3600,
        )

        with patch.object(manager, "_refresh_token", new=AsyncMock(return_value=new_token)):
            token = await manager.get_access_token(1)

        assert token == "fresh-token"
        assert manager._tokens[1].access_token == "fresh-token"

    @pytest.mark.asyncio
    async def test_refreshes_token_near_expiry(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        buffer = OAuth2TokenInfo.REFRESH_BUFFER_SECONDS
        near_expiry = time.time() + buffer - 5
        manager._tokens[1] = OAuth2TokenInfo(
            access_token="expiring-token",
            refresh_token="refresh",
            expires_at=near_expiry,
        )

        new_token = OAuth2TokenInfo(
            access_token="refreshed-token",
            refresh_token="refresh",
            expires_at=time.time() + 3600,
        )

        with patch.object(manager, "_refresh_token", new=AsyncMock(return_value=new_token)):
            token = await manager.get_access_token(1)

        assert token == "refreshed-token"


class TestOAuth2ManagerRefreshToken:
    """Tests for OAuth2Manager._refresh_token."""

    @pytest.mark.asyncio
    async def test_raises_if_not_oauth2_account(self, encryption_manager, oauth2_account):
        oauth2_account.auth_method = "basic"
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            with pytest.raises(OAuth2TokenError, match="not OAuth2"):
                await manager._refresh_token(1)

    @pytest.mark.asyncio
    async def test_raises_if_no_refresh_token(self, encryption_manager, oauth2_account):
        oauth2_account.oauth2_refresh_token = None
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            with pytest.raises(OAuth2TokenError, match="No refresh token"):
                await manager._refresh_token(1)

    @pytest.mark.asyncio
    async def test_raises_if_no_client_id(self, encryption_manager, oauth2_account):
        oauth2_account.oauth2_client_id = None
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            with pytest.raises(OAuth2TokenError, match="no OAuth2 client_id"):
                await manager._refresh_token(1)

    @pytest.mark.asyncio
    async def test_raises_if_no_client_secret(self, encryption_manager, oauth2_account):
        oauth2_account.oauth2_client_secret = None
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            with pytest.raises(OAuth2TokenError, match="no OAuth2 client_secret"):
                await manager._refresh_token(1)

    @pytest.mark.asyncio
    async def test_successful_refresh(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "https://mail.google.com/",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)), \
             patch("imap.oauth2_manager.httpx.AsyncClient", return_value=mock_client), \
             patch.object(manager, "_store_tokens", new=AsyncMock()) as mock_store:

            token = await manager._refresh_token(1)

        assert token.access_token == "new-access"
        mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_handles_provider_error(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Token expired",
        }
        mock_response.text = '{"error": "invalid_grant"}'

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)), \
             patch("imap.oauth2_manager.httpx.AsyncClient", return_value=mock_client):

            with pytest.raises(OAuth2ProviderError, match="invalid_grant"):
                await manager._refresh_token(1)

    @pytest.mark.asyncio
    async def test_refresh_handles_non_json_error(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = Exception("Not JSON")
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)), \
             patch("imap.oauth2_manager.httpx.AsyncClient", return_value=mock_client):

            with pytest.raises(OAuth2TokenError, match="Token refresh failed"):
                await manager._refresh_token(1)

    @pytest.mark.asyncio
    async def test_refresh_uses_account_scopes_if_set(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_scopes = "custom.scope"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

        captured_data = {}

        async def capture_post(url, data=None, **kwargs):
            captured_data["data"] = data
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = capture_post

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)), \
             patch("imap.oauth2_manager.httpx.AsyncClient", return_value=mock_client), \
             patch.object(manager, "_store_tokens", new=AsyncMock()):

            await manager._refresh_token(1)

        assert captured_data["data"]["scope"] == "custom.scope"

    @pytest.mark.asyncio
    async def test_refresh_uses_provider_default_scopes(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_scopes = None

        captured_data = {}

        async def capture_post(url, data=None, **kwargs):
            captured_data["data"] = data
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            }
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = capture_post

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)), \
             patch("imap.oauth2_manager.httpx.AsyncClient", return_value=mock_client), \
             patch.object(manager, "_store_tokens", new=AsyncMock()):

            await manager._refresh_token(1)

        assert "https://mail.google.com/" in captured_data["data"]["scope"]


class TestOAuth2ManagerStoreTokens:
    """Tests for OAuth2Manager._store_tokens."""

    @pytest.mark.asyncio
    async def test_stores_encrypted_tokens(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        token_info = OAuth2TokenInfo(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at=time.time() + 3600,
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = oauth2_account
        mock_session.execute.return_value = mock_result

        with patch("imap.oauth2_manager.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager._store_tokens(1, token_info)

        assert oauth2_account.oauth2_access_token is not None
        assert oauth2_account.oauth2_refresh_token is not None
        assert oauth2_account.oauth2_token_expiry is not None
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_if_account_not_found(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        token_info = OAuth2TokenInfo(
            access_token="tok",
            refresh_token="ref",
            expires_at=time.time() + 3600,
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("imap.oauth2_manager.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(OAuth2TokenError, match="not found"):
                await manager._store_tokens(999, token_info)


class TestOAuth2ManagerInitializeToken:
    """Tests for OAuth2Manager.initialize_token."""

    @pytest.mark.asyncio
    async def test_exchanges_auth_code_for_tokens(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "initial-access",
            "refresh_token": "initial-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_session = AsyncMock()
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = oauth2_account
        mock_session.execute.return_value = mock_session_result

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)), \
             patch("imap.oauth2_manager.httpx.AsyncClient", return_value=mock_client), \
             patch("imap.oauth2_manager.async_session_factory", return_value=mock_session):

            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            token = await manager.initialize_token(
                account_id=1,
                authorization_code="auth-code-123",
                provider="gmail",
                redirect_uri="http://localhost/callback",
            )

        assert token.access_token == "initial-access"
        assert token.refresh_token == "initial-refresh"
        assert oauth2_account.auth_method == "oauth2"
        assert oauth2_account.oauth2_provider == "gmail"

    @pytest.mark.asyncio
    async def test_uses_provided_client_credentials(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        captured_data = {}

        async def capture_post(url, data=None, **kwargs):
            captured_data["data"] = data
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "tok",
                "refresh_token": "ref",
                "expires_in": 3600,
            }
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = capture_post

        mock_session = AsyncMock()
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = oauth2_account
        mock_session.execute.return_value = mock_session_result

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)), \
             patch("imap.oauth2_manager.httpx.AsyncClient", return_value=mock_client), \
             patch("imap.oauth2_manager.async_session_factory", return_value=mock_session):

            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            await manager.initialize_token(
                account_id=1,
                authorization_code="code",
                client_id="custom-id",
                client_secret="custom-secret",
                scopes="custom.scope",
            )

        assert captured_data["data"]["client_id"] == "custom-id"
        assert captured_data["data"]["client_secret"] == "custom-secret"
        assert captured_data["data"]["scope"] == "custom.scope"

    @pytest.mark.asyncio
    async def test_raises_if_no_client_id(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_client_id = None

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            with pytest.raises(OAuth2TokenError, match="no OAuth2 client_id"):
                await manager.initialize_token(1, "code")

    @pytest.mark.asyncio
    async def test_raises_if_no_client_secret(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_client_secret = None

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            with pytest.raises(OAuth2TokenError, match="no OAuth2 client_secret"):
                await manager.initialize_token(1, "code")


class TestOAuth2ManagerSetRefreshToken:
    """Tests for OAuth2Manager.set_refresh_token."""

    @pytest.mark.asyncio
    async def test_stores_encrypted_refresh_token(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = oauth2_account
        mock_session.execute.return_value = mock_result

        with patch("imap.oauth2_manager.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.set_refresh_token(1, "new-refresh-token")

        assert oauth2_account.oauth2_refresh_token is not None
        decrypted = encryption_manager.decrypt(oauth2_account.oauth2_refresh_token)
        assert decrypted == "new-refresh-token"
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_if_account_not_found(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("imap.oauth2_manager.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(OAuth2TokenError, match="not found"):
                await manager.set_refresh_token(999, "token")


class TestOAuth2ManagerRevokeTokens:
    """Tests for OAuth2Manager.revoke_tokens."""

    @pytest.mark.asyncio
    async def test_clears_cache_and_database(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        manager._tokens[1] = OAuth2TokenInfo(
            access_token="tok",
            refresh_token="ref",
            expires_at=time.time() + 3600,
        )
        manager._locks[1] = MagicMock()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = oauth2_account
        mock_session.execute.return_value = mock_result

        with patch("imap.oauth2_manager.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await manager.revoke_tokens(1)

        assert 1 not in manager._tokens
        assert 1 not in manager._locks
        assert oauth2_account.auth_method == "basic"
        assert oauth2_account.oauth2_access_token is None
        assert oauth2_account.oauth2_refresh_token is None
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_if_account_not_found(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("imap.oauth2_manager.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(OAuth2TokenError, match="not found"):
                await manager.revoke_tokens(999)


class TestOAuth2ManagerIsTokenValid:
    """Tests for OAuth2Manager.is_token_valid."""

    @pytest.mark.asyncio
    async def test_returns_false_if_account_not_found(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        with patch.object(manager, "_get_account", new=AsyncMock(side_effect=OAuth2TokenError("not found"))):
            result = await manager.is_token_valid(999)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_if_not_oauth2(self, encryption_manager, basic_auth_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=basic_auth_account)):
            result = await manager.is_token_valid(1)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_if_no_expiry(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_token_expiry = None

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            result = await manager.is_token_valid(1)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_if_token_not_expired(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            result = await manager.is_token_valid(1)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_if_token_expired(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            result = await manager.is_token_valid(1)

        assert result is False


class TestOAuth2ManagerGetTokenInfo:
    """Tests for OAuth2Manager.get_token_info."""

    @pytest.mark.asyncio
    async def test_returns_token_status(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            info = await manager.get_token_info(1)

        assert info["account_id"] == 1
        assert info["auth_method"] == "oauth2"
        assert info["provider"] == "gmail"
        assert info["has_access_token"] is True
        assert info["has_refresh_token"] is True
        assert info["is_expired"] is False
        assert info["seconds_until_expiry"] > 0

    @pytest.mark.asyncio
    async def test_returns_expired_status(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            info = await manager.get_token_info(1)

        assert info["is_expired"] is True
        assert info["seconds_until_expiry"] < 0

    @pytest.mark.asyncio
    async def test_returns_no_expiry_info(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        oauth2_account.oauth2_token_expiry = None

        with patch.object(manager, "_get_account", new=AsyncMock(return_value=oauth2_account)):
            info = await manager.get_token_info(1)

        assert info["token_expiry"] is None
        assert info["is_expired"] is True
        assert info["seconds_until_expiry"] == 0


class TestOAuth2ManagerRemoveToken:
    """Tests for OAuth2Manager.remove_token."""

    def test_removes_cached_token(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        manager._tokens[1] = OAuth2TokenInfo(
            access_token="tok",
            refresh_token="ref",
            expires_at=time.time() + 3600,
        )
        manager._locks[1] = MagicMock()

        manager.remove_token(1)

        assert 1 not in manager._tokens
        assert 1 not in manager._locks

    def test_safe_to_call_for_nonexistent_account(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        manager.remove_token(999)


class TestOAuth2ManagerGetAccount:
    """Tests for OAuth2Manager._get_account."""

    @pytest.mark.asyncio
    async def test_fetches_account(self, encryption_manager, oauth2_account):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = oauth2_account
        mock_session.execute.return_value = mock_result

        with patch("imap.oauth2_manager.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            account = await manager._get_account(1)

        assert account == oauth2_account

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("imap.oauth2_manager.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(OAuth2TokenError, match="not found"):
                await manager._get_account(999)


class TestOAuth2ManagerEncryptDecrypt:
    """Tests for OAuth2Manager._encrypt_field and _decrypt_field."""

    def test_encrypt_decrypt_roundtrip(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        plaintext = "sensitive-data"
        encrypted = manager._encrypt_field(plaintext)
        decrypted = manager._decrypt_field(encrypted)
        assert decrypted == plaintext

    def test_decrypt_none_returns_none(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        assert manager._decrypt_field(None) is None

    def test_decrypt_invalid_returns_none(self, encryption_manager):
        manager = OAuth2Manager(encryption_manager=encryption_manager)
        assert manager._decrypt_field("not-valid-encrypted-data") is None
