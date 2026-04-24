"""Async SMTP client for sending emails with attachments.

Implements secure SMTP connections with TLS/SSL, supports OAuth2 XOAUTH2
and basic authentication, and builds multipart MIME messages with attachments.
"""

import asyncio
import logging
import mimetypes
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Any, Callable, Coroutine

import aiosmtplib

logger = logging.getLogger(__name__)


class SMTPConnectionError(Exception):
    """Raised when SMTP connection cannot be established."""

    pass


class SMTPAuthenticationError(Exception):
    """Raised when SMTP authentication fails."""

    pass


class SMTPRetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""

    pass


class SMTOPOperationError(Exception):
    """Raised when an SMTP operation fails after successful connection."""

    pass


class SMTPClient:
    """Async SMTP client for sending emails.

    Manages secure SMTP connections, handles authentication (OAuth2/Basic),
    builds multipart MIME messages, and sends emails with attachments.

    Attributes:
        host: SMTP server hostname
        port: SMTP server port (default 587 for STARTTLS, 465 for SSL)
        username: Account username for authentication
        password: Account password or OAuth2 access token
        use_tls: Whether to use STARTTLS (port 587)
        use_ssl: Whether to use implicit SSL (port 465)
        use_oauth: Whether to use OAuth2 XOAUTH2 authentication
        ssl_context: SSL context for secure connections
        timeout: Connection timeout in seconds
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for exponential backoff
        oauth2_token_callback: Optional async callback to refresh OAuth2 tokens
    """

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        use_oauth: bool = False,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        oauth2_token_callback: Callable[[], Coroutine[None, None, str]] | None = None,
    ) -> None:
        """Initialize the SMTP client with connection parameters.

        Args:
            host: SMTP server hostname
            port: SMTP server port (default 587 for STARTTLS)
            username: Account username for authentication
            password: Account password or OAuth2 access token
            use_tls: Whether to use STARTTLS (default True for port 587)
            use_ssl: Whether to use implicit SSL (default False, set True for port 465)
            use_oauth: Whether to use OAuth2 XOAUTH2 authentication
            ssl_context: Optional custom SSL context
            timeout: Connection timeout in seconds
            max_retries: Maximum number of retry attempts
            backoff_factor: Multiplier for exponential backoff
            oauth2_token_callback: Optional async callable that returns a fresh
                OAuth2 access token when the current one expires
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.use_oauth = use_oauth
        self.ssl_context = ssl_context or self._create_default_ssl_context()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.oauth2_token_callback = oauth2_token_callback

        self._client: aiosmtplib.SMTP | None = None
        self._connected = False

    @staticmethod
    def _create_default_ssl_context() -> ssl.SSLContext:
        """Create a secure default SSL context for SMTP connections.

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
            SMTPRetryExhaustedError: When all retry attempts have been exhausted
        """
        last_exception: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except (aiosmtplib.SMTPException, ConnectionError, OSError) as e:
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

        raise SMTPRetryExhaustedError(
            f"Operation '{operation}' failed after {self.max_retries} attempts: {last_exception}"
        ) from last_exception

    async def connect(self) -> None:
        """Establish a secure SMTP connection and authenticate.

        Creates a TLS/SSL connection to the SMTP server and authenticates
        using either basic auth or OAuth2 XOAUTH2 mechanism.

        Raises:
            SMTPConnectionError: When connection cannot be established
            SMTPAuthenticationError: When authentication credentials are invalid
        """
        if self._connected:
            logger.debug("Already connected to SMTP server")
            return

        try:
            self._client = aiosmtplib.SMTP(
                hostname=self.host,
                port=self.port,
                timeout=self.timeout,
                use_tls=self.use_ssl,
            )

            await self._client.connect()

            if self.use_tls and not self.use_ssl:
                await self._client.starttls(tls_context=self.ssl_context)

            await self._retry_with_backoff(
                "SMTP authentication",
                self._authenticate,
            )

            self._connected = True
            logger.info(f"Successfully connected to {self.host}:{self.port}")

        except SMTPAuthenticationError:
            raise
        except Exception as e:
            await self.disconnect()
            raise SMTPConnectionError(
                f"Failed to connect to {self.host}:{self.port}: {e}"
            ) from e

    async def _authenticate(self) -> None:
        """Perform SMTP authentication.

        Uses either basic LOGIN or OAuth2 XOAUTH2 mechanism based on configuration.
        If OAuth2 authentication fails and a token refresh callback is available,
        attempts to refresh the token and retry once.

        Raises:
            SMTPAuthenticationError: When authentication fails
        """
        if self._client is None:
            raise SMTPConnectionError("SMTP client not initialized")

        try:
            if self.use_oauth:
                await self._authenticate_oauth2()
            else:
                await self._authenticate_basic()
        except SMTPAuthenticationError:
            raise
        except aiosmtplib.SMTPException as e:
            raise SMTPAuthenticationError(f"SMTP authentication error: {e}") from e

    async def _authenticate_oauth2(self) -> None:
        """Authenticate using OAuth2 XOAUTH2 mechanism.

        Attempts authentication with the current token. If it fails and
        a token refresh callback is available, refreshes the token and retries.

        Raises:
            SMTPAuthenticationError: When authentication fails after refresh attempt
        """
        if self._client is None:
            raise SMTPConnectionError("SMTP client not initialized")

        try:
            await self._client.login(self.username, self.password, use_oauth2=True)
        except aiosmtplib.SMTPAuthenticationError:
            if self.oauth2_token_callback:
                await self._refresh_and_retry_oauth2()
            else:
                raise SMTPAuthenticationError("OAuth2 SMTP authentication failed")

    async def _refresh_and_retry_oauth2(self) -> None:
        """Refresh OAuth2 token and retry SMTP authentication.

        Raises:
            SMTPAuthenticationError: When authentication fails after token refresh
        """
        if self._client is None:
            raise SMTPConnectionError("SMTP client not initialized")

        try:
            new_token = await self.oauth2_token_callback()
            self.password = new_token
        except Exception as e:
            raise SMTPAuthenticationError(
                f"OAuth2 token refresh failed: {e}"
            ) from e

        try:
            await self._client.login(self.username, self.password, use_oauth2=True)
        except aiosmtplib.SMTPAuthenticationError:
            raise SMTPAuthenticationError(
                "OAuth2 SMTP authentication failed after token refresh"
            )

    async def _authenticate_basic(self) -> None:
        """Authenticate using basic username/password login.

        Raises:
            SMTPAuthenticationError: When basic authentication fails
        """
        if self._client is None:
            raise SMTPConnectionError("SMTP client not initialized")

        try:
            await self._client.login(self.username, self.password)
        except aiosmtplib.SMTPAuthenticationError as e:
            raise SMTPAuthenticationError(f"Basic SMTP authentication failed: {e}") from e

    async def disconnect(self) -> None:
        """Gracefully close the SMTP connection.

        Sends QUIT command and cleans up client resources.
        Safe to call multiple times or when not connected.
        """
        if self._client is not None:
            try:
                if self._connected:
                    await self._client.quit()
                    logger.info(f"Disconnected from {self.host}:{self.port}")
            except Exception as e:
                logger.warning(f"Error during SMTP disconnect: {e}")
            finally:
                self._client = None

        self._connected = False

    async def send_email(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        html: str | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        from_name: str | None = None,
        attachments: list[str] | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Send an email message via SMTP.

        Builds a multipart MIME message with optional HTML body and attachments,
        then sends it to the specified recipients.

        Args:
            to: Recipient email address or list of addresses
            subject: Email subject line
            body: Plain text email body
            html: Optional HTML email body
            cc: Optional CC recipient(s)
            bcc: Optional BCC recipient(s)
            from_name: Optional display name for the sender
            attachments: Optional list of file paths to attach
            reply_to: Optional Reply-To address

        Returns:
            Dictionary with send confirmation including message_id and recipients

        Raises:
            SMTPConnectionError: If not connected to SMTP server
            SMTOPOperationError: If the send operation fails
        """
        if not self._connected or self._client is None:
            raise SMTPConnectionError("Not connected to SMTP server")

        to_list = [to] if isinstance(to, str) else to
        cc_list = [cc] if isinstance(cc, str) else (cc or [])
        bcc_list = [bcc] if isinstance(bcc, str) else (bcc or [])

        self._validate_addresses(to_list, "to")
        if cc_list:
            self._validate_addresses(cc_list, "cc")
        if bcc_list:
            self._validate_addresses(bcc_list, "bcc")

        message = self._build_message(
            to=to_list,
            subject=subject,
            body=body,
            html=html,
            cc=cc_list,
            bcc=bcc_list,
            from_name=from_name,
            attachments=attachments,
            reply_to=reply_to,
        )

        async def _send() -> dict[str, Any]:
            if self._client is None:
                raise SMTPConnectionError("SMTP client not initialized")

            all_recipients = to_list + (cc_list or []) + (bcc_list or [])
            response = await self._client.send_message(message, all_recipients)

            logger.info(
                f"Email sent to {', '.join(to_list)} with subject '{subject}'"
            )

            return {
                "status": "sent",
                "message_id": message["Message-ID"],
                "recipients": all_recipients,
                "smtp_response": str(response),
            }

        try:
            return await self._retry_with_backoff("Send email", _send)
        except Exception as e:
            raise SMTOPOperationError(f"Failed to send email: {e}") from e

    def _build_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        from_name: str | None = None,
        attachments: list[str] | None = None,
        reply_to: str | None = None,
    ) -> MIMEMultipart:
        """Build a multipart MIME message.

        Args:
            to: List of recipient email addresses
            subject: Email subject line
            body: Plain text email body
            html: Optional HTML email body
            cc: Optional list of CC addresses
            bcc: Optional list of BCC addresses
            from_name: Optional display name for the sender
            attachments: Optional list of file paths to attach
            reply_to: Optional Reply-To address

        Returns:
            A fully constructed MIMEMultipart message ready to send
        """
        msg = MIMEMultipart("mixed")

        sender_display = from_name or self.username
        msg["From"] = formataddr((sender_display, self.username))
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()

        if cc:
            msg["Cc"] = ", ".join(cc)

        if reply_to:
            msg["Reply-To"] = reply_to

        # Build body part
        if html:
            alt_part = MIMEMultipart("alternative")
            alt_part.attach(MIMEText(body, "plain", "utf-8"))
            alt_part.attach(MIMEText(html, "html", "utf-8"))
            msg.attach(alt_part)
        else:
            msg.attach(MIMEText(body, "plain", "utf-8"))

        # Attach files
        if attachments:
            for file_path in attachments:
                attachment = self._create_attachment(file_path)
                msg.attach(attachment)

        return msg

    def _create_attachment(self, file_path: str) -> MIMEApplication:
        """Create a MIME attachment from a file path.

        Args:
            file_path: Path to the file to attach

        Returns:
            MIMEApplication object ready to be attached to a message

        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If the file cannot be read
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Attachment file not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Attachment path is not a file: {file_path}")

        content = path.read_bytes()
        filename = path.name

        content_type, _ = mimetypes.guess_type(filename)
        if content_type is None:
            content_type = "application/octet-stream"

        attachment = MIMEApplication(content, Name=filename)
        attachment["Content-Disposition"] = f'attachment; filename="{filename}"'
        attachment.add_header("Content-ID", f"<{filename}>")

        return attachment

    @staticmethod
    def _validate_addresses(addresses: list[str], label: str) -> None:
        """Validate email address format for a list of addresses.

        Args:
            addresses: List of email addresses to validate
            label: Label for error messages (e.g., 'to', 'cc', 'bcc')

        Raises:
            ValueError: If any address is empty or missing '@' symbol
        """
        for addr in addresses:
            if not addr or not addr.strip():
                raise ValueError(f"{label} address cannot be empty")
            if "@" not in addr:
                raise ValueError(f"Invalid {label} address: {addr}")

    @property
    def is_connected(self) -> bool:
        """Check if the client is currently connected to the SMTP server.

        Returns:
            True if connected, False otherwise
        """
        return self._connected

    async def __aenter__(self) -> "SMTPClient":
        """Async context manager entry - connects to SMTP server.

        Returns:
            Self for use in async with statements
        """
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - disconnects from SMTP server.

        Args:
            exc_type: Exception type if an error occurred
            exc_val: Exception value if an error occurred
            exc_tb: Traceback if an error occurred
        """
        await self.disconnect()
