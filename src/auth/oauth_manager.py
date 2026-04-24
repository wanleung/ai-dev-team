"""OAuth2 token manager for Calendar MCP Service.

Handles OAuth2 authentication flows, token storage, refresh logic, and
credential validation for both Google and Microsoft providers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from src.config.settings import settings

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    def __init__(self, message: str, provider: Optional[str] = None) -> None:
        """Initialize authentication error.

        Args:
            message: Error message describing the authentication failure.
            provider: Optional provider name for context.
        """
        super().__init__(message)
        self.provider = provider


class OAuthManager:
    """Manages OAuth2 tokens and authentication for calendar providers.

    Handles token storage, refresh logic, and credential validation
    for Google and Microsoft identity providers. Tokens are stored
    in memory and refreshed automatically when nearing expiry.
    """

    # Buffer before expiry to trigger refresh (5 minutes)
    _REFRESH_BUFFER = timedelta(minutes=5)

    def __init__(self) -> None:
        """Initialize OAuth manager with empty token cache."""
        self._token_cache: dict[str, dict[str, Any]] = {}
        self._refresh_locks: dict[str, bool] = {}
        self._initialize_tokens()

    def _initialize_tokens(self) -> None:
        """Load initial tokens from configuration.

        Reads access and refresh tokens from settings for both
        Google and Outlook providers if they are configured.
        """
        if settings.google_access_token:
            self._token_cache["google"] = {
                "access_token": settings.google_access_token,
                "refresh_token": settings.google_refresh_token,
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            }
            self._refresh_locks["google"] = False

        if settings.outlook_access_token:
            self._token_cache["outlook"] = {
                "access_token": settings.outlook_access_token,
                "refresh_token": settings.outlook_refresh_token,
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            }
            self._refresh_locks["outlook"] = False

    def set_token(
        self,
        provider: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: int = 3600,
    ) -> None:
        """Set or update tokens for a provider.

        Args:
            provider: Provider name ('google' or 'outlook').
            access_token: New access token.
            refresh_token: Optional refresh token (keeps existing if None).
            expires_in: Token lifetime in seconds (default 1 hour).
        """
        existing = self._token_cache.get(provider, {})
        self._token_cache[provider] = {
            "access_token": access_token,
            "refresh_token": refresh_token or existing.get("refresh_token"),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        }
        self._refresh_locks[provider] = False
        logger.info(f"Token set for provider: {provider}")

    async def get_credentials(self, provider: str) -> str:
        """Get valid credentials for the specified provider.

        Returns the current access token, refreshing it automatically
        if it has expired or is about to expire.

        Args:
            provider: Provider name ('google' or 'outlook').

        Returns:
            Valid access token string.

        Raises:
            ValueError: If provider is not supported.
            AuthenticationError: If credentials cannot be obtained.
        """
        if provider not in self._token_cache:
            raise AuthenticationError(
                f"No credentials configured for provider: {provider}",
                provider=provider,
            )

        token_info = self._token_cache[provider]
        now = datetime.now(timezone.utc)

        # Check if token needs refresh
        if now >= token_info["expires_at"] - self._REFRESH_BUFFER:
            refresh_token = token_info.get("refresh_token")
            if refresh_token:
                await self._refresh_token(provider, refresh_token)
            else:
                raise AuthenticationError(
                    f"Token expired and no refresh token available for {provider}",
                    provider=provider,
                )

        return self._token_cache[provider]["access_token"]

    async def refresh_token(self, provider: str, refresh_token: str) -> dict[str, Any]:
        """Refresh an access token using the refresh token.

        Args:
            provider: Provider name ('google' or 'outlook').
            refresh_token: Refresh token to use.

        Returns:
            Dictionary with new token information including access_token,
            refresh_token, and expires_at.

        Raises:
            ValueError: If provider is not supported.
            AuthenticationError: If refresh fails.
        """
        if provider == "google":
            return await self._refresh_google_token(refresh_token)
        elif provider == "outlook":
            return await self._refresh_outlook_token(refresh_token)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    async def validate_token(self, provider: str, access_token: str) -> bool:
        """Validate an access token with the provider.

        Makes a lightweight API call to verify the token is still valid.

        Args:
            provider: Provider name ('google' or 'outlook').
            access_token: Access token to validate.

        Returns:
            True if token is valid, False otherwise.
        """
        try:
            if provider == "google":
                return await self._validate_google_token(access_token)
            elif provider == "outlook":
                return await self._validate_outlook_token(access_token)
            else:
                logger.warning(f"Cannot validate token for unknown provider: {provider}")
                return False
        except Exception as e:
            logger.error(f"Token validation failed for {provider}: {e}")
            return False

    async def _refresh_token(self, provider: str, refresh_token: str) -> None:
        """Refresh token with simple locking to prevent concurrent refreshes.

        Args:
            provider: Provider name.
            refresh_token: Refresh token to use.
        """
        if self._refresh_locks.get(provider, False):
            logger.debug(f"Token refresh already in progress for {provider}, waiting")
            return

        try:
            self._refresh_locks[provider] = True
            await self.refresh_token(provider, refresh_token)
            logger.info(f"Token refreshed for provider: {provider}")
        except AuthenticationError as e:
            logger.error(f"Token refresh failed for {provider}: {e}")
            raise
        finally:
            self._refresh_locks[provider] = False

    async def _refresh_google_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh Google OAuth2 token.

        Args:
            refresh_token: Google refresh token.

        Returns:
            New token information dictionary.

        Raises:
            AuthenticationError: If token refresh fails.
        """
        if not settings.google_client_id or not settings.google_client_secret:
            raise AuthenticationError(
                "Google OAuth2 credentials not configured",
                provider="google",
            )

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": settings.google_client_id,
                        "client_secret": settings.google_client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise AuthenticationError(
                    f"Google token refresh failed: {e.response.text}",
                    provider="google",
                ) from e
            except httpx.RequestError as e:
                raise AuthenticationError(
                    f"Google token refresh request failed: {e}",
                    provider="google",
                ) from e

            token_data = response.json()

            self._token_cache["google"] = {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", refresh_token),
                "expires_at": datetime.now(timezone.utc)
                + timedelta(seconds=token_data.get("expires_in", 3600)),
            }

            return self._token_cache["google"]

    async def _refresh_outlook_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh Microsoft OAuth2 token.

        Args:
            refresh_token: Microsoft refresh token.

        Returns:
            New token information dictionary.

        Raises:
            AuthenticationError: If token refresh fails.
        """
        if (
            not settings.outlook_client_id
            or not settings.outlook_client_secret
        ):
            raise AuthenticationError(
                "Outlook OAuth2 credentials not configured",
                provider="outlook",
            )

        token_url = (
            f"https://login.microsoftonline.com/{settings.outlook_tenant_id}"
            f"/oauth2/v2.0/token"
        )

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    token_url,
                    data={
                        "client_id": settings.outlook_client_id,
                        "client_secret": settings.outlook_client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                        "scope": " ".join(settings.outlook_scopes),
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise AuthenticationError(
                    f"Outlook token refresh failed: {e.response.text}",
                    provider="outlook",
                ) from e
            except httpx.RequestError as e:
                raise AuthenticationError(
                    f"Outlook token refresh request failed: {e}",
                    provider="outlook",
                ) from e

            token_data = response.json()

            self._token_cache["outlook"] = {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", refresh_token),
                "expires_at": datetime.now(timezone.utc)
                + timedelta(seconds=token_data.get("expires_in", 3600)),
            }

            return self._token_cache["outlook"]

    async def _validate_google_token(self, access_token: str) -> bool:
        """Validate a Google access token.

        Args:
            access_token: Google access token to validate.

        Returns:
            True if token is valid.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"access_token": access_token},
                timeout=10.0,
            )
            return response.status_code == 200

    async def _validate_outlook_token(self, access_token: str) -> bool:
        """Validate a Microsoft Graph access token.

        Args:
            access_token: Microsoft Graph access token to validate.

        Returns:
            True if token is valid.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            return response.status_code == 200

    def is_token_expired(self, provider: str) -> bool:
        """Check if a provider's token is expired.

        Args:
            provider: Provider name.

        Returns:
            True if token is expired or not configured.
        """
        if provider not in self._token_cache:
            return True

        token_info = self._token_cache[provider]
        return datetime.now(timezone.utc) >= token_info["expires_at"]

    def get_token_info(self, provider: str) -> Optional[dict[str, Any]]:
        """Get token information for a provider (without the access token).

        Args:
            provider: Provider name.

        Returns:
            Dictionary with token metadata or None if not configured.
        """
        if provider not in self._token_cache:
            return None

        token_info = self._token_cache[provider]
        return {
            "has_refresh_token": bool(token_info.get("refresh_token")),
            "expires_at": token_info["expires_at"],
            "is_expired": self.is_token_expired(provider),
        }
