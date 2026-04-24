"""MCP tool: add_account - Register a new IMAP email account for syncing."""

import json
import logging

from config.settings import get_settings
from db.models import EmailAccount
from db.session import async_session_factory

logger = logging.getLogger(__name__)


async def add_account(
    email_address: str,
    imap_host: str,
    imap_port: int = 993,
    username: str = "",
    password: str = "",
    user_id: str = "default",
    auth_method: str = "basic",
) -> str:
    """Register a new IMAP email account for syncing.

    Args:
        email_address: The email address for this account.
        imap_host: IMAP server hostname.
        imap_port: IMAP server port (default 993 for SSL).
        username: IMAP username (often the same as email_address).
        password: IMAP password (will be encrypted before storage).
        user_id: The user who owns this account.
        auth_method: Authentication method: 'basic' or 'oauth2'.

    Returns:
        JSON string with the new account ID and status.
    """
    settings = get_settings()
    encryption_manager = settings.get_encryption_manager()
    encrypted_password = encryption_manager.encrypt(password)

    account = EmailAccount(
        user_id=user_id,
        email_address=email_address,
        imap_host=imap_host,
        imap_port=imap_port,
        username=username or email_address,
        encrypted_password=encrypted_password,
        auth_method=auth_method,
        is_active=True,
    )

    async with async_session_factory() as session:
        session.add(account)
        await session.commit()
        await session.refresh(account)

    return json.dumps({
        "id": account.id,
        "status": "created",
        "email_address": account.email_address,
    })
