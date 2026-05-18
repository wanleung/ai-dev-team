"""Async IMAP operations package.

Provides IMAP client, connection pooling, and OAuth2 token management
for secure email account access.
"""

from imap.client import (
    IMAPClient,
    IMAPConnectionError,
    IMAPAuthenticationError,
    IMAPRetryExhaustedError,
    IMAPOperationError,
)
from imap.connection_pool import IMAPConnectionPool
from imap.oauth2_manager import OAuth2Manager, OAuth2TokenError

__all__ = [
    "IMAPClient",
    "IMAPConnectionError",
    "IMAPAuthenticationError",
    "IMAPRetryExhaustedError",
    "IMAPOperationError",
    "IMAPConnectionPool",
    "OAuth2Manager",
    "OAuth2TokenError",
]
