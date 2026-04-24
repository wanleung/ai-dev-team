"""OAuth2 token lifecycle manager for IMAP accounts.

Handles automatic token refresh before expiry, stores refresh tokens
in the database, and provides valid access tokens for IMAP authentication.

Supports multiple OAuth2 providers (Gmail, Outlook, Yahoo) with configurable
token endpoints and per-account credential storage.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import EncryptionManager, get_encryption_manager
from db.models import EmailAccount
from db.session import async_session_factory

logger = logging.getLogger(__name__)


# Default OAuth2 provider configurations
PROVIDER_CONFIGS: dict[str, dict] = {
    "gmail": {
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": ["https://mail.google.com/"],
    },
    "outlook": {
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": ["https://outlook.office.com/IMAP.AccessAsUser.All", "offline_access"],
    },
    "yahoo": {
        "token_url": "https://api.login.yahoo.com/oauth2/get_token",
        "scopes": ["mail-r"],
    },
}


class OAuth2TokenError(Exception):
    """Raised when OAuth2 token operations fail."""

    pass


class OAuth2ProviderError(OAuth2TokenError):
    """Raised when OAuth2 provider returns an error response."""

    def __init__(self, error: str, description: str = "") -> None:
        self.error = error
        self.description = description
        super().__init__(f"OAuth2 provider error: {error} - {description}")


class OAuth2TokenInfo:
    """Holds OAuth2 token data with expiry tracking.

    Attributes:
        access_token: The current access token
        refresh_token: The refresh token for obtaining new access tokens
        expires_at: Unix timestamp when the access token expires
        token_type: Token type (typically 'Bearer')
        scope: OAuth2 scope granted
    """

    # Refresh token 5 minutes before expiry to avoid race conditions
    REFRESH_BUFFER_SECONDS = 300

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        token_type: str = "Bearer",
        scope: str = "",
    ) -> None:
        """Initialize OAuth2 token info.

        Args:
            access_token: The current access token
            refresh_token: The refresh token for obtaining new access tokens
            expires_at: Unix timestamp when the access token expires
            token_type: Token type (typically 'Bearer')
            scope: OAuth2 scope granted
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.token_type = token_type
        self.scope = scope

    @property
    def is_expired(self) -> bool:
        """Check if the access token has expired or is about to expire.

        Returns:
            True if the token is expired or will expire within the refresh buffer.
        """
        return time.time() >= (self.expires_at - self.REFRESH_BUFFER_SECONDS)

    @classmethod
    def from_token_response(cls, response: dict, refresh_token: str) -> "OAuth2TokenInfo":
        """Create OAuth2TokenInfo from a token endpoint response.

        Args:
            response: JSON response from the OAuth2 token endpoint
            refresh_token: The refresh token (may not be in response if unchanged)

        Returns:
            A new OAuth2TokenInfo instance
        """
        expires_in = response.get("expires_in", 3600)
        expires_at = time.time() + expires_in

        return cls(
            access_token=response["access_token"],
            refresh_token=response.get("refresh_token", refresh_token),
            expires_at=expires_at,
            token_type=response.get("token_type", "Bearer"),
            scope=response.get("scope", ""),
        )


class OAuth2Manager:
    """Manages OAuth2 token lifecycle for email accounts.

    Stores refresh tokens encrypted in the database, handles automatic
    token refresh before expiry, and provides valid access tokens for
    IMAP XOAUTH2 authentication.

    Supports multiple providers with per-account client credentials.

    Attributes:
        encryption_manager: EncryptionManager for encrypting stored tokens
        default_timeout: HTTP request timeout in seconds
        _tokens: In-memory cache of tokens per account_id
        _locks: Per-account asyncio locks for thread-safe token refresh
    """

    def __init__(
        self,
        encryption_manager: EncryptionManager | None = None,
        default_timeout: float = 30.0,
    ) -> None:
        """Initialize the OAuth2 manager.

        Args:
            encryption_manager: Optional encryption manager (uses default if None)
            default_timeout: HTTP timeout for token requests in seconds
        """
        self.encryption_manager = encryption_manager or get_encryption_manager()
        self.default_timeout = default_timeout

        self._tokens: dict[int, OAuth2TokenInfo] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def get_provider_config(provider: str) -> dict:
        """Get OAuth2 configuration for a known provider.

        Args:
            provider: Provider name (e.g., 'gmail', 'outlook', 'yahoo')

        Returns:
            Dictionary with token_url and scopes

        Raises:
            OAuth2TokenError: If provider is not recognized
        """
        provider_lower = provider.lower()
        if provider_lower not in PROVIDER_CONFIGS:
            raise OAuth2TokenError(f"Unknown OAuth2 provider: {provider}")
        return PROVIDER_CONFIGS[provider_lower]

    def _get_lock(self, account_id: int) -> asyncio.Lock:
        """Get or create a lock for a specific account.

        Args:
            account_id: Account identifier

        Returns:
            An asyncio.Lock for the account
        """
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    async def _get_account(self, account_id: int) -> EmailAccount:
        """Fetch an email account from the database.

        Args:
            account_id: Account primary key

        Returns:
            EmailAccount instance

        Raises:
            OAuth2TokenError: If account not found
        """
        async with async_session_factory() as session:
            stmt = select(EmailAccount).where(EmailAccount.id == account_id)
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()

            if account is None:
                raise OAuth2TokenError(f"Account {account_id} not found")

            return account

    def _decrypt_field(self, encrypted_value: str | None) -> str | None:
        """Decrypt an encrypted field value.

        Args:
            encrypted_value: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext or None if input is None
        """
        if encrypted_value is None:
            return None
        try:
            return self.encryption_manager.decrypt(encrypted_value)
        except Exception as e:
            logger.error(f"Failed to decrypt OAuth2 field: {e}")
            return None

    def _encrypt_field(self, plaintext: str) -> str:
        """Encrypt a plaintext value for database storage.

        Args:
            plaintext: Sensitive string to encrypt

        Returns:
            Base64-encoded encrypted string
        """
        return self.encryption_manager.encrypt(plaintext)

    async def get_access_token(self, account_id: int) -> str:
        """Get a valid access token for an account, refreshing if necessary.

        Checks the in-memory cache first. If the token is expired or about
        to expire, triggers a refresh using the stored refresh token.

        Args:
            account_id: The email account ID

        Returns:
            A valid access token string

        Raises:
            OAuth2TokenError: If token retrieval or refresh fails
            ValueError: If the account does not exist or has no OAuth2 credentials
        """
        async with self._get_lock(account_id):
            token_info = self._tokens.get(account_id)

            if token_info and not token_info.is_expired:
                return token_info.access_token

            token_info = await self._refresh_token(account_id)
            self._tokens[account_id] = token_info
            return token_info.access_token

    async def _refresh_token(self, account_id: int) -> OAuth2TokenInfo:
        """Refresh the access token for an account using the stored refresh token.

        Args:
            account_id: The email account ID

        Returns:
            A new OAuth2TokenInfo with fresh access token

        Raises:
            OAuth2TokenError: If the refresh fails
        """
        account = await self._get_account(account_id)

        if account.auth_method != "oauth2":
            raise OAuth2TokenError(
                f"Account {account_id} uses auth method '{account.auth_method}', not OAuth2"
            )

        refresh_token = self._decrypt_field(account.oauth2_refresh_token)
        if not refresh_token:
            raise OAuth2TokenError(f"No refresh token available for account {account_id}")

        provider = account.oauth2_provider or "gmail"
        config = self.get_provider_config(provider)

        client_id = account.oauth2_client_id
        client_secret = self._decrypt_field(account.oauth2_client_secret)

        if not client_id:
            raise OAuth2TokenError(f"Account {account_id} has no OAuth2 client_id configured")
        if not client_secret:
            raise OAuth2TokenError(f"Account {account_id} has no OAuth2 client_secret configured")

        # Build scopes
        if account.oauth2_scopes:
            scope = account.oauth2_scopes
        else:
            scope = " ".join(config["scopes"])

        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            response = await client.post(
                config["token_url"],
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": scope,
                },
            )

            if response.status_code != 200:
                try:
                    error_json = response.json()
                    raise OAuth2ProviderError(
                        error=error_json.get("error", "unknown"),
                        description=error_json.get("error_description", response.text),
                    )
                except OAuth2ProviderError:
                    raise
                except Exception:
                    raise OAuth2TokenError(
                        f"Token refresh failed for account {account_id}: "
                        f"{response.status_code} {response.text}"
                    )

            token_data = response.json()
            token_info = OAuth2TokenInfo.from_token_response(token_data, refresh_token)

            # Persist updated tokens to database
            await self._store_tokens(account_id, token_info)

            logger.info(f"Successfully refreshed OAuth2 token for account {account_id}")
            return token_info

    async def _store_tokens(self, account_id: int, token_info: OAuth2TokenInfo) -> None:
        """Encrypt and store OAuth2 tokens in the database.

        Args:
            account_id: Account ID to update
            token_info: Token info with fresh tokens
        """
        async with async_session_factory() as session:
            stmt = select(EmailAccount).where(EmailAccount.id == account_id)
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()
            if account is None:
                raise OAuth2TokenError(f"Account {account_id} not found")

            account.oauth2_access_token = self._encrypt_field(token_info.access_token)
            account.oauth2_refresh_token = self._encrypt_field(token_info.refresh_token)
            account.oauth2_token_expiry = datetime.fromtimestamp(
                token_info.expires_at, tz=timezone.utc
            )
            await session.commit()

    async def initialize_token(
        self,
        account_id: int,
        authorization_code: str,
        provider: str = "gmail",
        redirect_uri: str = "",
        client_id: str | None = None,
        client_secret: str | None = None,
        scopes: str | None = None,
    ) -> OAuth2TokenInfo:
        """Exchange an authorization code for initial tokens.

        Called after the OAuth2 authorization flow completes to obtain
        and store the initial access and refresh tokens.

        Args:
            account_id: The email account ID
            authorization_code: The OAuth2 authorization code
            provider: OAuth2 provider name (default 'gmail')
            redirect_uri: OAuth2 redirect URI used in authorization
            client_id: OAuth2 client ID (uses account default if None)
            client_secret: OAuth2 client secret (uses account default if None)
            scopes: Space-separated OAuth2 scopes

        Returns:
            OAuth2TokenInfo with the initial tokens

        Raises:
            OAuth2TokenError: If the token exchange fails
        """
        account = await self._get_account(account_id)
        config = self.get_provider_config(provider)

        # Use provided credentials or fall back to account defaults
        cid = client_id or account.oauth2_client_id
        csecret = client_secret or self._decrypt_field(account.oauth2_client_secret)

        if not cid:
            raise OAuth2TokenError(f"No OAuth2 client_id configured for account {account_id}")
        if not csecret:
            raise OAuth2TokenError(f"No OAuth2 client_secret configured for account {account_id}")

        # Use provided scopes or provider defaults
        scope = scopes or " ".join(config["scopes"])

        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            response = await client.post(
                config["token_url"],
                data={
                    "client_id": cid,
                    "client_secret": csecret,
                    "code": authorization_code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "scope": scope,
                },
            )

            if response.status_code != 200:
                try:
                    error_json = response.json()
                    raise OAuth2ProviderError(
                        error=error_json.get("error", "unknown"),
                        description=error_json.get("error_description", response.text),
                    )
                except OAuth2ProviderError:
                    raise
                except Exception:
                    raise OAuth2TokenError(
                        f"Token exchange failed for account {account_id}: "
                        f"{response.status_code} {response.text}"
                    )

            token_data = response.json()
            token_info = OAuth2TokenInfo.from_token_response(
                token_data, token_data.get("refresh_token", "")
            )

            # Update account with OAuth2 configuration and persist
            async with async_session_factory() as session:
                stmt = select(EmailAccount).where(EmailAccount.id == account_id)
                result = await session.execute(stmt)
                account = result.scalar_one_or_none()
                if account is None:
                    raise OAuth2TokenError(f"Account {account_id} not found")

                account.auth_method = "oauth2"
                account.oauth2_provider = provider
                account.oauth2_client_id = cid
                if client_secret:
                    account.oauth2_client_secret = self._encrypt_field(client_secret)
                if scopes:
                    account.oauth2_scopes = scopes

                account.oauth2_access_token = self._encrypt_field(token_info.access_token)
                account.oauth2_refresh_token = self._encrypt_field(token_info.refresh_token)
                account.oauth2_token_expiry = datetime.fromtimestamp(
                    token_info.expires_at, tz=timezone.utc
                )
                await session.commit()

            self._tokens[account_id] = token_info

            logger.info(f"Successfully initialized OAuth2 tokens for account {account_id}")
            return token_info

    async def set_refresh_token(self, account_id: int, refresh_token: str) -> None:
        """Store a new refresh token for an account in the database.

        Args:
            account_id: The email account ID
            refresh_token: The refresh token to store

        Raises:
            OAuth2TokenError: If the account does not exist
        """
        async with async_session_factory() as session:
            stmt = select(EmailAccount).where(EmailAccount.id == account_id)
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()
            if account is None:
                raise OAuth2TokenError(f"Account {account_id} not found")
            account.oauth2_refresh_token = self._encrypt_field(refresh_token)
            await session.commit()

    async def revoke_tokens(self, account_id: int) -> None:
        """Revoke and clear OAuth2 tokens for an account.

        Removes tokens from cache and database, reverts auth method to basic.

        Args:
            account_id: The email account ID
        """
        self._tokens.pop(account_id, None)
        self._locks.pop(account_id, None)

        async with async_session_factory() as session:
            stmt = select(EmailAccount).where(EmailAccount.id == account_id)
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()
            if account is None:
                raise OAuth2TokenError(f"Account {account_id} not found")
            account.auth_method = "basic"
            account.oauth2_access_token = None
            account.oauth2_refresh_token = None
            account.oauth2_token_expiry = None
            await session.commit()
        logger.info(f"Revoked OAuth2 tokens for account {account_id}")

    async def is_token_valid(self, account_id: int) -> bool:
        """Check if an account has a valid (non-expired) access token.

        Args:
            account_id: Account primary key

        Returns:
            True if token exists and is not expired
        """
        try:
            account = await self._get_account(account_id)
        except OAuth2TokenError:
            return False

        if account.auth_method != "oauth2":
            return False

        if account.oauth2_token_expiry is None:
            return False

        return datetime.now(timezone.utc) < account.oauth2_token_expiry

    async def get_token_info(self, account_id: int) -> dict:
        """Get token status information for an account.

        Args:
            account_id: Account primary key

        Returns:
            Dictionary with token status, provider, expiry info
        """
        account = await self._get_account(account_id)

        info: dict = {
            "account_id": account_id,
            "auth_method": account.auth_method,
            "provider": account.oauth2_provider,
            "has_access_token": account.oauth2_access_token is not None,
            "has_refresh_token": account.oauth2_refresh_token is not None,
        }

        if account.oauth2_token_expiry:
            now = datetime.now(timezone.utc)
            info["token_expiry"] = account.oauth2_token_expiry.isoformat()
            info["is_expired"] = now >= account.oauth2_token_expiry
            info["seconds_until_expiry"] = int(
                (account.oauth2_token_expiry - now).total_seconds()
            )
        else:
            info["token_expiry"] = None
            info["is_expired"] = True
            info["seconds_until_expiry"] = 0

        return info

    def remove_token(self, account_id: int) -> None:
        """Remove cached tokens for an account.

        Use this when an account is deactivated or removed.
        Does not modify the database.

        Args:
            account_id: The email account ID
        """
        self._tokens.pop(account_id, None)
        self._locks.pop(account_id, None)
