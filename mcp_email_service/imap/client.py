"""Async IMAP client wrapper with connection lifecycle and retry/backoff logic.

Implements the IMAP Connector Service for secure IMAP connections,
authentication (OAuth2/Basic), and mailbox operations.
"""

import asyncio
import logging
import ssl
from email.message import Message as EmailMessage
from email.parser import BytesParser
from typing import Any, Callable, Coroutine

import aioimaplib

logger = logging.getLogger(__name__)


class IMAPConnectionError(Exception):
    """Raised when IMAP connection operations fail."""

    pass


class IMAPAuthenticationError(Exception):
    """Raised when IMAP authentication fails."""

    pass


class IMAPRetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""

    pass


class IMAPOperationError(Exception):
    """Raised when an IMAP operation fails after successful connection."""

    pass


class IMAPClient:
    """Async IMAP client wrapper with retry/backoff logic.

    Manages secure IMAP connections, handles authentication (OAuth2/Basic),
    and executes raw mailbox operations (fetch, search, select folder).

    Attributes:
        host: IMAP server hostname
        port: IMAP server port (default 993 for SSL)
        username: Account username for authentication
        password: Account password or OAuth2 token
        use_oauth: Whether to use OAuth2 authentication
        ssl_context: SSL context for secure connections
        timeout: Connection timeout in seconds
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for exponential backoff
        oauth2_token_callback: Optional async callback to refresh OAuth2 tokens
    """

    def __init__(
        self,
        host: str,
        port: int = 993,
        username: str = "",
        password: str = "",
        use_oauth: bool = False,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        oauth2_token_callback: Callable[[], Coroutine[None, None, str]] | None = None,
    ) -> None:
        """Initialize the IMAP client with connection parameters.

        Args:
            host: IMAP server hostname
            port: IMAP server port (default 993 for SSL)
            username: Account username for authentication
            password: Account password or OAuth2 token
            use_oauth: Whether to use OAuth2 authentication
            ssl_context: Optional custom SSL context
            timeout: Connection timeout in seconds
            max_retries: Maximum number of retry attempts for operations
            backoff_factor: Multiplier for exponential backoff between retries
            oauth2_token_callback: Optional async callable that returns a fresh
                OAuth2 access token when the current one expires
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_oauth = use_oauth
        self.ssl_context = ssl_context or self._create_default_ssl_context()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.oauth2_token_callback = oauth2_token_callback

        self._client: aioimaplib.IMAP4_SSL | None = None
        self._connected = False
        self._selected_folder: str | None = None

    @staticmethod
    def _create_default_ssl_context() -> ssl.SSLContext:
        """Create a secure default SSL context for IMAP connections.

        Returns:
            Configured SSL context with TLS 1.2+ requirement
        """
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    async def _retry_with_backoff(self, operation: str, func, *args, **kwargs) -> Any:
        """Execute an operation with exponential backoff retry logic.

        Args:
            operation: Human-readable name of the operation for logging
            func: Async callable to execute
            *args: Positional arguments for the callable
            **kwargs: Keyword arguments for the callable

        Returns:
            Result of the successful operation

        Raises:
            IMAPRetryExhaustedError: When all retry attempts have been exhausted
            IMAPConnectionError: When connection-specific errors occur
        """
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except (aioimaplib.IMAP4Error, ConnectionError, OSError) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    wait_time = self.backoff_factor**attempt
                    logger.warning(
                        f"{operation} failed (attempt {attempt + 1}/{self.max_retries}): {e}. "
                        f"Retrying in {wait_time:.1f}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"{operation} failed after {self.max_retries} attempts: {e}"
                    )

        raise IMAPRetryExhaustedError(
            f"Operation '{operation}' failed after {self.max_retries} attempts: {last_exception}"
        ) from last_exception

    async def connect(self) -> None:
        """Establish a secure IMAP connection and authenticate.

        Creates an SSL connection to the IMAP server and authenticates
        using either basic auth or OAuth2 XOAUTH2 mechanism.

        Raises:
            IMAPConnectionError: When connection cannot be established
            IMAPAuthenticationError: When authentication credentials are invalid
        """
        if self._connected:
            logger.debug("Already connected to IMAP server")
            return

        try:
            self._client = aioimaplib.IMAP4_SSL(
                host=self.host,
                port=self.port,
                ssl_context=self.ssl_context,
                timeout=self.timeout,
            )

            await self._retry_with_backoff(
                "IMAP connection",
                self._authenticate,
            )

            self._connected = True
            logger.info(f"Successfully connected to {self.host}:{self.port}")

        except IMAPAuthenticationError:
            raise
        except Exception as e:
            await self.disconnect()
            raise IMAPConnectionError(f"Failed to connect to {self.host}:{self.port}: {e}") from e

    async def _authenticate(self) -> None:
        """Perform IMAP authentication with the server.

        Uses either basic LOGIN or OAuth2 XOAUTH2 mechanism based on configuration.
        If OAuth2 authentication fails and a token refresh callback is available,
        attempts to refresh the token and retry authentication once.

        Raises:
            IMAPAuthenticationError: When authentication fails
        """
        if self._client is None:
            raise IMAPConnectionError("IMAP client not initialized")

        try:
            if self.use_oauth:
                await self._authenticate_oauth2()
            else:
                await self._authenticate_basic()

        except IMAPAuthenticationError:
            raise
        except aioimaplib.IMAP4Error as e:
            raise IMAPAuthenticationError(f"IMAP authentication error: {e}") from e

    async def _authenticate_oauth2(self) -> None:
        """Authenticate using OAuth2 XOAUTH2 mechanism.

        Attempts authentication with the current token. If it fails and
        a token refresh callback is available, refreshes the token and retries.

        Raises:
            IMAPAuthenticationError: When authentication fails after refresh attempt
        """
        if self._client is None:
            raise IMAPConnectionError("IMAP client not initialized")

        if not self.password:
            if self.oauth2_token_callback:
                await self._refresh_and_retry_oauth2()
                return
            raise IMAPAuthenticationError("OAuth2 access token is empty")

        auth_string = f"user={self.username}\x01auth=Bearer {self.password}\x01\x01"
        result = await self._client.authenticate("XOAUTH2", lambda x: auth_string)

        if result.result != "OK":
            if self.oauth2_token_callback:
                await self._refresh_and_retry_oauth2()
            else:
                raise IMAPAuthenticationError(
                    f"OAuth2 authentication failed: {result.result} {result.data}"
                )

    async def _refresh_and_retry_oauth2(self) -> None:
        """Refresh OAuth2 token and retry authentication.

        Raises:
            IMAPAuthenticationError: When authentication fails after token refresh
        """
        if self._client is None:
            raise IMAPConnectionError("IMAP client not initialized")

        try:
            new_token = await self.oauth2_token_callback()
            if not new_token:
                raise IMAPAuthenticationError("OAuth2 token callback returned empty token")
            self.password = new_token
        except IMAPAuthenticationError:
            raise
        except Exception as e:
            raise IMAPAuthenticationError(
                f"OAuth2 token refresh failed: {e}"
            ) from e

        auth_string = f"user={self.username}\x01auth=Bearer {self.password}\x01\x01"
        result = await self._client.authenticate("XOAUTH2", lambda x: auth_string)

        if result.result != "OK":
            raise IMAPAuthenticationError(
                f"OAuth2 authentication failed after token refresh: "
                f"{result.result} {result.data}"
            )

    async def _authenticate_basic(self) -> None:
        """Authenticate using basic username/password login.

        Raises:
            IMAPAuthenticationError: When basic authentication fails
        """
        if self._client is None:
            raise IMAPConnectionError("IMAP client not initialized")

        result = await self._client.login(self.username, self.password)

        if result.result != "OK":
            raise IMAPAuthenticationError(
                f"Authentication failed: {result.result} {result.data}"
            )

    async def disconnect(self) -> None:
        """Gracefully close the IMAP connection.

        Sends LOGOUT command and cleans up client resources.
        Safe to call multiple times or when not connected.
        """
        if self._client is not None:
            try:
                if self._connected:
                    await self._client.logout()
                    logger.info(f"Disconnected from {self.host}:{self.port}")
            except Exception as e:
                logger.warning(f"Error during IMAP disconnect: {e}")
            finally:
                self._client = None

        self._connected = False
        self._selected_folder = None

    async def select_folder(self, folder: str = "INBOX", readonly: bool = False) -> dict[str, int]:
        """Select an IMAP mailbox folder for operations.

        Args:
            folder: Folder name to select (default: INBOX)
            readonly: Whether to open in read-only mode (EXAMINE vs SELECT)

        Returns:
            Dictionary with folder status information including message count

        Raises:
            IMAPConnectionError: When not connected to IMAP server
            IMAPOperationError: When folder selection fails
        """
        if not self._connected or self._client is None:
            raise IMAPConnectionError("Not connected to IMAP server")

        async def _select() -> dict[str, int]:
            if self._client is None:
                raise IMAPConnectionError("IMAP client not initialized")

            method = self._client.select if not readonly else self._client.examine
            result = await method(folder)

            if result.result != "OK":
                raise IMAPOperationError(
                    f"Failed to select folder '{folder}': {result.result} {result.data}"
                )

            # Parse response to get message count and other info
            info = {}
            if result.data and len(result.data) > 0:
                # Parse IMAP response data for EXISTS, RECENT, etc.
                for item in result.data:
                    if isinstance(item, bytes):
                        parts = item.decode().split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            info[parts[1].lower()] = int(parts[0])

            self._selected_folder = folder
            return info

        try:
            return await self._retry_with_backoff(f"Select folder '{folder}'", _select)
        except Exception as e:
            raise IMAPOperationError(f"Failed to select folder '{folder}': {e}") from e

    async def fetch_messages(
        self,
        message_set: str = "1:*",
        items: str = "(BODY.PEEK[])",
        folder: str | None = None,
    ) -> list[EmailMessage]:
        """Fetch email messages from the selected IMAP folder.

        Uses BODY.PEEK[] to avoid marking messages as read.

        Args:
            message_set: IMAP message sequence set (e.g., "1:*", "1:10", "42")
            items: IMAP fetch items specification
            folder: Optional folder to select before fetching

        Returns:
            List of parsed email.message.Message objects

        Raises:
            IMAPConnectionError: When not connected to IMAP server
            IMAPOperationError: When fetch operation fails
        """
        if not self._connected or self._client is None:
            raise IMAPConnectionError("Not connected to IMAP server")

        if folder:
            await self.select_folder(folder)

        async def _fetch() -> list[EmailMessage]:
            if self._client is None:
                raise IMAPConnectionError("IMAP client not initialized")

            result = await self._client.fetch(message_set, items)

            if result.result != "OK":
                raise IMAPOperationError(
                    f"Failed to fetch messages: {result.result} {result.data}"
                )

            messages = []
            parser = BytesParser()

            # Parse the raw RFC822 messages from the response
            for item in result.data:
                if isinstance(item, bytes) and b"RFC822" in item:
                    # Extract the raw email content
                    # IMAP response format: * FETCH (UID X BODY[] {size}\r\n<content>)
                    if b"\r\n" in item:
                        parts = item.split(b"\r\n", 1)
                        if len(parts) > 1:
                            try:
                                msg = parser.parsebytes(parts[1])
                                messages.append(msg)
                            except Exception as e:
                                logger.warning(f"Failed to parse email message: {e}")

            return messages

        try:
            return await self._retry_with_backoff("Fetch messages", _fetch)
        except Exception as e:
            raise IMAPOperationError(f"Failed to fetch messages: {e}") from e

    async def search_messages(
        self,
        criteria: str = "ALL",
        folder: str | None = None,
        charset: str = "UTF-8",
    ) -> list[int]:
        """Search for messages in the selected IMAP folder.

        Args:
            criteria: IMAP search criteria (e.g., "UNSEEN", "FROM example@test.com", "SINCE 01-Jan-2024")
            folder: Optional folder to select before searching
            charset: Character set for the search

        Returns:
            List of message UIDs matching the search criteria

        Raises:
            IMAPConnectionError: When not connected to IMAP server
            IMAPOperationError: When search operation fails
        """
        if not self._connected or self._client is None:
            raise IMAPConnectionError("Not connected to IMAP server")

        if folder:
            await self.select_folder(folder)

        async def _search() -> list[int]:
            if self._client is None:
                raise IMAPConnectionError("IMAP client not initialized")

            result = await self._client.search(criteria, charset=charset)

            if result.result != "OK":
                raise IMAPOperationError(
                    f"Search failed: {result.result} {result.data}"
                )

            # Parse UIDs from response
            uids = []
            for item in result.data:
                if isinstance(item, bytes):
                    uid_str = item.decode().strip()
                    if uid_str:
                        uids.extend([int(uid) for uid in uid_str.split() if uid.isdigit()])

            return uids

        try:
            return await self._retry_with_backoff("Search messages", _search)
        except Exception as e:
            raise IMAPOperationError(f"Failed to search messages: {e}") from e

    async def mark_as_read(self, uid: int, folder: str | None = None) -> None:
        """Mark a specific message as read by adding the \\Seen flag.

        Args:
            uid: Message UID to mark as read
            folder: Optional folder containing the message

        Raises:
            IMAPConnectionError: When not connected to IMAP server
            IMAPOperationError: When the operation fails
        """
        if not self._connected or self._client is None:
            raise IMAPConnectionError("Not connected to IMAP server")

        if folder:
            await self.select_folder(folder)

        async def _mark() -> None:
            if self._client is None:
                raise IMAPConnectionError("IMAP client not initialized")

            result = await self._client.uid("STORE", str(uid), "+FLAGS", "\\Seen")

            if result.result != "OK":
                raise IMAPOperationError(
                    f"Failed to mark message {uid} as read: {result.result} {result.data}"
                )

        try:
            await self._retry_with_backoff(f"Mark message {uid} as read", _mark)
        except Exception as e:
            raise IMAPOperationError(f"Failed to mark message {uid} as read: {e}") from e

    async def list_folders(self) -> list[str]:
        """List all available IMAP mailbox folders.

        Returns:
            List of folder names available on the IMAP server

        Raises:
            IMAPConnectionError: When not connected to IMAP server
            IMAPOperationError: When the folder listing operation fails
        """
        if not self._connected or self._client is None:
            raise IMAPConnectionError("Not connected to IMAP server")

        async def _list() -> list[str]:
            if self._client is None:
                raise IMAPConnectionError("IMAP client not initialized")

            result = await self._client.list()

            if result.result != "OK":
                raise IMAPOperationError(
                    f"Failed to list folders: {result.result} {result.data}"
                )

            folders = []
            for item in result.data:
                if isinstance(item, bytes):
                    decoded = item.decode()
                    parts = decoded.split('"')
                    if len(parts) >= 2:
                        folders.append(parts[-2])
                    else:
                        folder_name = decoded.split()[-1].strip('"')
                        folders.append(folder_name)

            return folders

        try:
            return await self._retry_with_backoff("List folders", _list)
        except Exception as e:
            raise IMAPOperationError(f"Failed to list folders: {e}") from e

    async def get_uids(self, folder: str | None = None) -> list[int]:
        """Retrieve all UIDs in the specified or current folder.

        Args:
            folder: Optional folder to select before fetching UIDs

        Returns:
            List of all message UIDs in the folder

        Raises:
            IMAPConnectionError: When not connected to IMAP server
            IMAPOperationError: When the operation fails
        """
        return await self.search_messages("ALL", folder=folder)

    @property
    def is_connected(self) -> bool:
        """Check if the client is currently connected to the IMAP server.

        Returns:
            True if connected, False otherwise
        """
        return self._connected

    @property
    def selected_folder(self) -> str | None:
        """Get the currently selected IMAP folder.

        Returns:
            Name of the selected folder, or None if no folder is selected
        """
        return self._selected_folder

    async def __aenter__(self) -> "IMAPClient":
        """Async context manager entry - connects to IMAP server.

        Returns:
            Self for use in async with statements
        """
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - disconnects from IMAP server.

        Args:
            exc_type: Exception type if an error occurred
            exc_val: Exception value if an error occurred
            exc_tb: Traceback if an error occurred
        """
        await self.disconnect()
