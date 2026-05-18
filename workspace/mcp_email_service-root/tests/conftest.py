"""Enhanced shared pytest fixtures for MCP Email Service integration tests."""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from config.settings import EncryptionManager, Settings
from db.base import Base
from db.models import EmailAccount, EmailMessage, Attachment, SyncState


@pytest.fixture
def encryption_key():
    """Generate a Fernet encryption key for tests."""
    return Fernet.generate_key().decode()


@pytest.fixture
def encryption_manager(encryption_key):
    """Create an EncryptionManager with a test key."""
    return EncryptionManager(encryption_key.encode())


@pytest.fixture
def mock_settings(encryption_key):
    """Create test settings with in-memory SQLite and test encryption key."""
    with patch("config.settings.get_settings") as mock_get, \
         patch("config.settings.Settings") as MockSettings:
        settings = MagicMock(spec=Settings)
        settings.app_name = "MCP Email Service (Test)"
        settings.debug = True
        settings.secret_key = MagicMock()
        settings.secret_key.get_secret_value.return_value = "test-secret"
        settings.database_url = "sqlite+aiosqlite:///:memory:"
        settings.db_pool_size = 5
        settings.db_max_overflow = 2
        settings.db_echo = False
        settings.db_pool_timeout = 30
        settings.db_pool_recycle = 3600
        settings.encryption_key = encryption_key
        settings.default_imap_port = 993
        settings.imap_connection_timeout = 30
        settings.imap_max_retries = 3
        settings.imap_retry_delay = 1.0
        settings.sync_interval_seconds = 300
        settings.sync_batch_size = 100
        settings.mcp_transport = "stdio"
        settings.mcp_server_host = "0.0.0.0"
        settings.mcp_server_port = 8000
        settings.api_prefix = "/api"
        settings.cors_origins = ["*"]
        settings.allowed_hosts = ["*"]
        settings.attachment_storage_path = tempfile.mkdtemp()
        settings.max_attachment_size_mb = 25
        settings.is_sqlite = True

        def get_encryption_manager():
            return EncryptionManager(encryption_key.encode())

        settings.get_encryption_manager = get_encryption_manager
        settings.ensure_storage_path.return_value = None

        MockSettings.return_value = settings
        mock_get.return_value = settings
        yield settings


@pytest.fixture
def mock_get_encryption_manager(encryption_manager):
    """Mock get_encryption_manager to return test encryption manager."""
    with patch("config.settings.get_encryption_manager") as mock:
        mock.return_value = encryption_manager
        yield mock


@pytest.fixture
async def async_engine():
    """Create an async SQLite engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    """Create an async session factory for testing."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def db_session_factory(async_engine):
    """Create a session factory bound to the test engine for integration tests."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    return factory


@pytest.fixture
def test_account_data():
    """Return sample account data for tests."""
    return {
        "user_id": "test-user",
        "email_address": "test@example.com",
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "username": "test@example.com",
        "password": "secret-password",
    }


@pytest.fixture
def test_email_data():
    """Return sample email data for tests."""
    return {
        "account_id": 1,
        "uid": 100,
        "message_id": "<test123@example.com>",
        "subject": "Test Email Subject",
        "sender": "sender@example.com",
        "recipients": "recipient@example.com",
        "date_received": datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        "body_text": "This is the plain text body.",
        "body_html": "<html><body><p>This is the HTML body.</p></body></html>",
        "has_attachments": False,
        "is_read": False,
    }


@pytest.fixture
def sample_raw_email():
    """Return a raw RFC822 email as bytes for parser tests."""
    return (
        b"From: sender@example.com\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: Test Email\r\n"
        b"Message-ID: <test123@example.com>\r\n"
        b"Date: Mon, 15 Jan 2024 10:30:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"This is the plain text body of the test email."
    )


@pytest.fixture
def sample_raw_email_multipart():
    """Return a multipart raw RFC822 email with HTML body and attachment."""
    boundary = "boundary123"
    return (
        f"From: sender@example.com\r\n"
        f"To: recipient@example.com\r\n"
        f"Subject: Multipart Test Email\r\n"
        f"Message-ID: <multipart456@example.com>\r\n"
        f"Date: Mon, 15 Jan 2024 10:30:00 +0000\r\n"
        f"Content-Type: multipart/mixed; boundary=\"{boundary}\"\r\n"
        f"\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"Plain text body.\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"\r\n"
        f"<html><body><p>HTML body.</p></body></html>\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: application/pdf; name=\"report.pdf\"\r\n"
        f"Content-Disposition: attachment; filename=\"report.pdf\"\r\n"
        f"Content-Transfer-Encoding: base64\r\n"
        f"\r\n"
        f"JVBERi0xLjQKJeLjz9MK\r\n"
        f"--{boundary}--\r\n"
    ).encode()


@pytest.fixture
def sample_raw_email_html_only():
    """Return an HTML-only raw email."""
    return (
        b"From: sender@example.com\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: HTML Only Email\r\n"
        b"Message-ID: <htmlonly789@example.com>\r\n"
        b"Date: Mon, 15 Jan 2024 10:30:00 +0000\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><p>Hello <b>world</b>!</p></body></html>"
    )


@pytest.fixture
def sample_raw_email_with_dangerous_html():
    """Return a raw email with dangerous HTML for sanitization tests."""
    return (
        b"From: sender@example.com\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: Dangerous HTML Email\r\n"
        b"Message-ID: <dangerous@example.com>\r\n"
        b"Date: Mon, 15 Jan 2024 10:30:00 +0000\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><script>alert('xss')</script><p onclick='evil()'>Click me</p><a href='javascript:void(0)'>Link</a><p>Safe content</p></body></html>"
    )


@pytest.fixture
def sample_raw_email_encoded_subject():
    """Return a raw email with MIME-encoded subject."""
    return (
        b"From: sender@example.com\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: =?utf-8?B?VGVzdCBFbWFpbCDwn5Oo?=  # 'Test Email \xf0\x9f\x93\xa7' base64 encoded\r\n"
        b"Message-ID: <encoded@example.com>\r\n"
        b"Date: Mon, 15 Jan 2024 10:30:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Body text."
    )


@pytest.fixture
def mock_imap_client():
    """Create a mocked IMAPClient."""
    client = MagicMock()
    client.host = "imap.example.com"
    client.port = 993
    client.username = "test@example.com"
    client.password = "secret"
    client.use_oauth = False
    client.timeout = 30.0
    client.max_retries = 3
    client.backoff_factor = 2.0
    client._connected = True
    client._selected_folder = "INBOX"
    client.is_connected = True
    client.selected_folder = "INBOX"

    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.select_folder = AsyncMock(return_value={"exists": 10, "recent": 2})
    client.fetch_messages = AsyncMock(return_value=[])
    client.search_messages = AsyncMock(return_value=[1, 2, 3])
    client.mark_as_read = AsyncMock()
    client.get_uids = AsyncMock(return_value=[1, 2, 3, 4, 5])

    return client


@pytest.fixture
def mock_connection_pool(mock_imap_client):
    """Create a mocked IMAPConnectionPool."""
    pool = MagicMock()
    pool.max_connections_per_account = 3
    pool.idle_timeout = 300.0
    pool.health_check_interval = 60.0

    pool.connection = MagicMock()
    pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_imap_client)
    pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

    pool.get_connection = AsyncMock(return_value=mock_imap_client)
    pool.return_connection = AsyncMock()
    pool.start = AsyncMock()
    pool.stop = AsyncMock()
    pool.close_account_connections = AsyncMock()
    pool.get_pool_stats.return_value = {1: 1}

    return pool


@pytest.fixture
def mock_sync_manager(mock_connection_pool):
    """Create a mocked SyncManager."""
    from sync.manager import SyncManager
    from parser.email_parser import EmailParser

    manager = MagicMock(spec=SyncManager)
    manager.connection_pool = mock_connection_pool
    manager.parser = EmailParser()
    manager.sync_interval = 300
    manager.batch_size = 100
    manager._running = False
    manager._background_task = None

    manager.sync_account = AsyncMock(return_value={"INBOX": 5})
    manager.get_sync_state = AsyncMock(return_value=[
        {"folder_name": "INBOX", "last_synced_uid": 100, "last_synced_at": datetime.now(timezone.utc), "status": "idle"}
    ])
    manager.mark_read = AsyncMock()
    manager.start_background_sync = MagicMock()
    manager.stop_background_sync = AsyncMock()

    return manager


@pytest.fixture
def mock_oauth2_manager(encryption_manager):
    """Create a mocked OAuth2Manager."""
    from imap.oauth2_manager import OAuth2Manager

    manager = MagicMock(spec=OAuth2Manager)
    manager.encryption_manager = encryption_manager
    manager.default_timeout = 30.0
    manager._tokens = {}
    manager._locks = {}

    manager.get_access_token = AsyncMock(return_value="fresh-access-token")
    manager._refresh_token = AsyncMock()
    manager.initialize_token = AsyncMock()
    manager.set_refresh_token = AsyncMock()
    manager.revoke_tokens = AsyncMock()
    manager.is_token_valid = AsyncMock(return_value=True)
    manager.get_token_info = AsyncMock(return_value={
        "account_id": 1,
        "auth_method": "oauth2",
        "provider": "gmail",
        "has_access_token": True,
        "has_refresh_token": True,
        "token_expiry": "2024-12-31T23:59:59+00:00",
        "is_expired": False,
        "seconds_until_expiry": 3600,
    })
    manager.remove_token = MagicMock()

    return manager


@pytest.fixture
def mock_smtp_client():
    """Create a mocked SMTPClient."""
    from smtp.client import SMTPClient

    client = MagicMock(spec=SMTPClient)
    client.host = "smtp.example.com"
    client.port = 587
    client.username = "test@example.com"
    client.password = "secret"
    client.use_tls = True
    client.use_ssl = False
    client.use_oauth = False
    client._connected = True
    client.is_connected = True

    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.send_email = AsyncMock(return_value={
        "status": "sent",
        "message_id": "<test-msg@example.com>",
        "recipients": ["recipient@example.com"],
        "smtp_response": "250 OK",
    })

    return client


@pytest.fixture
def test_app(mock_settings, mock_get_encryption_manager):
    """Create a FastAPI test app with mocked dependencies."""
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession
    from unittest.mock import AsyncMock

    from api.accounts import router as accounts_router
    from api.emails import router as emails_router

    app = FastAPI(title="MCP Email Service Test")

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.delete = MagicMock()

    async def override_get_session():
        yield mock_session

    app.dependency_overrides = {}

    app.include_router(accounts_router)
    app.include_router(emails_router)
    app.dependency_overrides[None] = override_get_session

    return app, mock_session


@pytest.fixture
def create_test_app():
    """Factory fixture to create test apps with custom session mocks."""
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession
    from unittest.mock import AsyncMock

    from api.accounts import router as accounts_router
    from api.emails import router as emails_router

    def _create(session_mock=None):
        if session_mock is None:
            session_mock = AsyncMock(spec=AsyncSession)
            session_mock.execute = AsyncMock()
            session_mock.flush = AsyncMock()
            session_mock.refresh = AsyncMock()
            session_mock.commit = AsyncMock()
            session_mock.rollback = AsyncMock()
            session_mock.close = AsyncMock()
            session_mock.add = MagicMock()
            session_mock.delete = MagicMock()

        app = FastAPI(title="MCP Email Service Test")

        async def override_get_session():
            yield session_mock

        from db.session import get_session
        app.include_router(accounts_router)
        app.include_router(emails_router)
        app.dependency_overrides[get_session] = override_get_session

        return app, session_mock

    return _create


@pytest.fixture
def create_test_app_with_auth():
    """Factory fixture to create test apps with auth middleware."""
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession
    from unittest.mock import AsyncMock

    from api.accounts import router as accounts_router
    from api.emails import router as emails_router
    from api.attachments import router as attachments_router
    from middleware.auth import user_scoping_middleware

    def _create(session_mock=None, user_id="default"):
        if session_mock is None:
            session_mock = AsyncMock(spec=AsyncSession)
            session_mock.execute = AsyncMock()
            session_mock.flush = AsyncMock()
            session_mock.refresh = AsyncMock()
            session_mock.commit = AsyncMock()
            session_mock.rollback = AsyncMock()
            session_mock.close = AsyncMock()
            session_mock.add = MagicMock()
            session_mock.delete = MagicMock()

        app = FastAPI(title="MCP Email Service Test")

        async def override_get_session():
            yield session_mock

        from db.session import get_session
        app.include_router(accounts_router)
        app.include_router(emails_router)
        app.include_router(attachments_router)
        app.dependency_overrides[get_session] = override_get_session

        async def mock_middleware(request, call_next):
            from middleware.auth import UserContext
            request.state.user = UserContext(user_id=user_id, is_authenticated=user_id != "default")
            return await call_next(request)

        app.middleware("http")(mock_middleware)

        return app, session_mock

    return _create


@pytest.fixture
def mock_mcp_context():
    """Create a mocked MCP Context for tool tests."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    return ctx


@pytest.fixture
def mock_async_session_factory():
    """Mock async_session_factory for MCP tool tests."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.add = MagicMock()

    async def mock_session_ctx():
        yield mock_session

    with patch("mcp_server.tools.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_factory, mock_session


@pytest.fixture
def oauth2_account(encryption_manager):
    """Create an EmailAccount configured for OAuth2."""
    account = MagicMock()
    account.id = 1
    account.user_id = "test-user"
    account.email_address = "test@gmail.com"
    account.imap_host = "imap.gmail.com"
    account.imap_port = 993
    account.username = "test@gmail.com"
    account.auth_method = "oauth2"
    account.oauth2_provider = "gmail"
    account.oauth2_client_id = "test-client-id"
    account.oauth2_client_secret = encryption_manager.encrypt("test-client-secret")
    account.oauth2_refresh_token = encryption_manager.encrypt("test-refresh-token")
    account.oauth2_access_token = encryption_manager.encrypt("test-access-token")
    account.oauth2_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    account.oauth2_scopes = "https://mail.google.com/"
    account.is_active = True
    account.encrypted_password = encryption_manager.encrypt("dummy")
    return account


@pytest.fixture
def basic_auth_account(encryption_manager):
    """Create an EmailAccount configured for basic auth."""
    account = MagicMock()
    account.id = 1
    account.user_id = "test-user"
    account.email_address = "test@example.com"
    account.imap_host = "imap.example.com"
    account.imap_port = 993
    account.username = "test@example.com"
    account.auth_method = "basic"
    account.oauth2_provider = None
    account.oauth2_client_id = None
    account.oauth2_client_secret = None
    account.oauth2_refresh_token = None
    account.oauth2_access_token = None
    account.oauth2_token_expiry = None
    account.oauth2_scopes = None
    account.is_active = True
    account.encrypted_password = encryption_manager.encrypt("secret-password")
    return account


@pytest.fixture
async def seeded_db_session(db_session_factory, encryption_key):
    """Create a real SQLite DB session with seeded test data for integration tests."""
    encryption_mgr = EncryptionManager(encryption_key.encode())
    async with db_session_factory() as session:
        account = EmailAccount(
            user_id="test-user",
            email_address="test@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="test@example.com",
            encrypted_password=encryption_mgr.encrypt("secret-password"),
            is_active=True,
            auth_method="basic",
        )
        session.add(account)
        await session.flush()

        for i in range(5):
            msg = EmailMessage(
                account_id=account.id,
                uid=100 + i,
                message_id=f"<msg{i}@example.com>",
                subject=f"Test Email {i}",
                sender=f"sender{i}@example.com",
                recipients="recipient@example.com",
                date_received=datetime(2024, 1, 15, 10, 30, i, tzinfo=timezone.utc),
                body_text=f"Body text for email {i}",
                body_html=f"<html><body>HTML {i}</body></html>",
                has_attachments=(i == 0),
                is_read=(i % 2 == 0),
            )
            session.add(msg)
            await session.flush()

            if i == 0:
                att = Attachment(
                    message_id=msg.id,
                    filename="report.pdf",
                    content_type="application/pdf",
                    size_bytes=1024,
                    storage_path="/tmp/test_report.pdf",
                )
                session.add(att)

        await session.commit()

        yield session, account.id

        await session.rollback()
