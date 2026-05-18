"""MCP tool for sending emails via SMTP.

Registers the send_email tool on the FastMCP server instance.
"""

import json
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from config.settings import get_settings
from db.models import EmailAccount
from db.session import async_session_factory
from smtp.client import SMTPClient, SMTOPOperationError

logger = logging.getLogger(__name__)


def register_smtp_tools(
    mcp: FastMCP,
) -> None:
    """Register SMTP-related MCP tools on the given FastMCP server instance.

    Creates a fresh SMTP client per call using account credentials from the database.

    Args:
        mcp: The FastMCP server to register tools on.
    """

    @mcp.tool()
    async def send_email(
        account_id: int,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        html: Optional[str] = None,
        attachment_paths: Optional[str] = None,
    ) -> str:
        """Send an email via SMTP using a registered account.

        Args:
            account_id: The email account ID to send from.
            to: Comma-separated list of recipient email addresses.
            subject: Email subject line.
            body: Plain text body content.
            cc: Optional comma-separated list of CC recipients.
            bcc: Optional comma-separated list of BCC recipients.
            html: Optional HTML body content.
            attachment_paths: Optional comma-separated list of file paths to attach.

        Returns:
            JSON string with send confirmation.

        Raises:
            ValueError: If the account does not exist or is inactive.
            SMTOPOperationError: If the email cannot be sent.
        """
        settings = get_settings()
        encryption_manager = settings.get_encryption_manager()

        async with async_session_factory() as session:
            stmt = select(EmailAccount).where(EmailAccount.id == account_id)
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()

            if account is None:
                raise ValueError(f"Account {account_id} not found")

            if not account.is_active:
                raise ValueError(f"Account {account_id} is inactive")

            decrypted_password = encryption_manager.decrypt(
                account.encrypted_password
            )

        recipients = [addr.strip() for addr in to.split(",") if addr.strip()]
        if not recipients:
            raise ValueError("At least one recipient is required")

        cc_list = [addr.strip() for addr in cc.split(",")] if cc else None
        bcc_list = [addr.strip() for addr in bcc.split(",")] if bcc else None
        attachments = (
            [p.strip() for p in attachment_paths.split(",")]
            if attachment_paths
            else None
        )

        use_ssl = account.imap_port == 465
        smtp_port = 465 if use_ssl else 587

        smtp_host = account.imap_host.replace("imap", "smtp", 1)

        async with SMTPClient(
            host=smtp_host,
            port=smtp_port,
            username=account.username,
            password=decrypted_password,
            use_tls=not use_ssl,
            use_ssl=use_ssl,
            use_oauth=account.auth_method == "oauth2",
        ) as client:
            result = await client.send_email(
                to=recipients,
                subject=subject,
                body=body,
                html=html,
                cc=cc_list,
                bcc=bcc_list,
                from_name=account.email_address,
                attachments=attachments,
            )

        return json.dumps(result)
