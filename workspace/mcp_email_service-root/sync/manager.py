"""Sync & Cache Manager for MCP Email Service.

Implements UID tracking, incremental fetch scheduler, deduplication,
and background task runner for email synchronization.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from db.models import Attachment, EmailAccount, EmailMessage, SyncState
from imap.client import IMAPClient
from imap.connection_pool import IMAPConnectionPool
from parser.email_parser import EmailParser, ParsedEmail

logger = logging.getLogger(__name__)

DEFAULT_FOLDERS = ["INBOX"]


class SyncManager:
    """Manages incremental IMAP sync, UID tracking, deduplication, and background tasks.

    Coordinates the IMAP connector, email parser, and database layer to
    perform efficient incremental syncs per account and folder.

    Attributes:
        connection_pool: Shared IMAP connection pool
        parser: Email parser instance for MIME decoding
        sync_interval: Seconds between automatic sync runs
        batch_size: Max messages to process per sync batch
    """

    def __init__(
        self,
        connection_pool: IMAPConnectionPool,
        parser: Optional[EmailParser] = None,
        sync_interval: int = 300,
        batch_size: int = 100,
    ) -> None:
        """Initialize the sync manager.

        Args:
            connection_pool: IMAP connection pool for acquiring connections
            parser: Email parser instance; defaults to a new EmailParser()
            sync_interval: Background sync interval in seconds
            batch_size: Maximum messages to fetch per sync batch
        """
        self.connection_pool = connection_pool
        self.parser = parser or EmailParser()
        self.sync_interval = sync_interval
        self.batch_size = batch_size

        self._background_task: asyncio.Task | None = None
        self._running = False
        self._settings = get_settings()

    async def sync_account(
        self,
        account_id: int,
        session: AsyncSession,
        folders: Optional[list[str]] = None,
    ) -> dict[str, int]:
        """Perform an incremental sync for a single email account.

        Fetches new messages since the last synced UID per folder,
        parses them, deduplicates, and persists to the database.

        Args:
            account_id: The email account to sync
            session: Active database session
            folders: Optional list of folders to sync; defaults to INBOX

        Returns:
            Dictionary mapping folder name to number of messages synced

        Raises:
            ValueError: If the account does not exist
        """
        account = await self._get_account(session, account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")

        if not account.is_active:
            logger.info(f"Account {account_id} is inactive, skipping sync")
            return {}

        target_folders = folders or DEFAULT_FOLDERS
        results: dict[str, int] = {}

        decrypted_password = self._settings.get_encryption_manager().decrypt(
            account.encrypted_password
        )

        async with self.connection_pool.connection(
            account_id=account_id,
            host=account.imap_host,
            port=account.imap_port,
            username=account.username,
            password=decrypted_password,
        ) as client:
            for folder in target_folders:
                try:
                    synced = await self._sync_folder(
                        client, account_id, folder, session
                    )
                    results[folder] = synced
                except Exception as e:
                    logger.error(
                        f"Failed to sync folder '{folder}' for account {account_id}: {e}"
                    )
                    await self._update_sync_state(
                        session, account_id, folder, status="error"
                    )

        await session.commit()
        return results

    async def get_sync_state(
        self, session: AsyncSession, account_id: int
    ) -> list[dict]:
        """Retrieve the current sync state for all folders of an account.

        Args:
            session: Active database session
            account_id: The email account to query

        Returns:
            List of dicts with folder_name, last_synced_uid, last_synced_at, status
        """
        stmt = select(SyncState).where(SyncState.account_id == account_id)
        result = await session.execute(stmt)
        states = result.scalars().all()

        return [
            {
                "folder_name": s.folder_name,
                "last_synced_uid": s.last_synced_uid,
                "last_synced_at": s.last_synced_at,
                "status": s.status,
            }
            for s in states
        ]

    async def mark_read(
        self, session: AsyncSession, message_id: int, client: Optional[IMAPClient] = None
    ) -> None:
        """Mark an email as read in both the database and the IMAP server.

        Args:
            session: Active database session
            message_id: Database ID of the email message
            client: Optional pre-existing IMAP client; if None a new connection is created
        """
        stmt = select(EmailMessage).where(EmailMessage.id == message_id)
        result = await session.execute(stmt)
        msg = result.scalar_one_or_none()

        if msg is None:
            raise ValueError(f"Message {message_id} not found")

        msg.is_read = True

        if client is not None and client.is_connected:
            try:
                await client.mark_as_read(uid=msg.uid)
            except Exception as e:
                logger.warning(f"Failed to mark message {message_id} as read on IMAP: {e}")

        await session.commit()

    def start_background_sync(self) -> None:
        """Start the background sync scheduler task.

        Must be called from within a running event loop.
        The scheduler iterates all active accounts and syncs them.
        """
        if self._running:
            logger.warning("Background sync is already running")
            return

        self._running = True
        self._background_task = asyncio.create_task(self._background_sync_loop())
        logger.info("Background sync scheduler started")

    async def stop_background_sync(self) -> None:
        """Stop the background sync scheduler gracefully."""
        self._running = False
        if self._background_task is not None:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
            self._background_task = None
        logger.info("Background sync scheduler stopped")

    async def _background_sync_loop(self) -> None:
        """Main background loop that periodically syncs all active accounts."""
        while self._running:
            try:
                await asyncio.sleep(self.sync_interval)
                if not self._running:
                    break

                async with async_session_factory() as session:
                    stmt = select(EmailAccount).where(EmailAccount.is_active == True)
                    result = await session.execute(stmt)
                    accounts = result.scalars().all()

                    for account in accounts:
                        try:
                            await self.sync_account(account.id, session)
                        except Exception as e:
                            logger.error(
                                f"Background sync failed for account {account.id}: {e}"
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background sync loop error: {e}")

    async def _sync_folder(
        self,
        client: IMAPClient,
        account_id: int,
        folder: str,
        session: AsyncSession,
    ) -> int:
        """Sync a single folder for an account using incremental UID fetch.

        Args:
            client: Connected IMAP client
            account_id: Account identifier
            folder: Folder name to sync
            session: Active database session

        Returns:
            Number of new messages synced
        """
        await self._update_sync_state(session, account_id, folder, status="syncing")

        sync_state = await self._get_or_create_sync_state(
            session, account_id, folder
        )
        last_uid = sync_state.last_synced_uid

        # Fetch UIDs greater than the last synced UID
        all_uids = await client.get_uids(folder=folder)
        new_uids = [uid for uid in all_uids if uid > last_uid]

        if not new_uids:
            await self._update_sync_state(
                session, account_id, folder, uid=last_uid, status="idle"
            )
            return 0

        # Limit to batch size
        new_uids = new_uids[: self.batch_size]

        # Build UID set for IMAP fetch
        uid_set = ",".join(str(uid) for uid in new_uids)

        messages = await client.fetch_messages(
            message_set=uid_set,
            items="(UID BODY.PEEK[])",
            folder=folder,
        )

        synced_count = 0
        max_uid = last_uid

        for msg in messages:
            try:
                parsed = self.parser.parse_message(msg)
                uid = self._extract_uid_from_message(msg)

                if uid is None:
                    continue

                if uid > max_uid:
                    max_uid = uid

                # Deduplicate by message_id header
                exists = await self._message_exists(session, account_id, parsed.message_id)
                if exists:
                    logger.debug(
                        f"Skipping duplicate message {parsed.message_id} for account {account_id}"
                    )
                    continue

                await self._persist_email(session, account_id, uid, parsed)
                synced_count += 1
            except Exception as e:
                logger.warning(f"Failed to process message in folder '{folder}': {e}")

        await self._update_sync_state(
            session, account_id, folder, uid=max_uid, status="idle"
        )

        logger.info(
            f"Synced {synced_count} new messages from '{folder}' for account {account_id}"
        )
        return synced_count

    async def _get_account(
        self, session: AsyncSession, account_id: int
    ) -> Optional[EmailAccount]:
        """Fetch an email account by ID."""
        stmt = select(EmailAccount).where(EmailAccount.id == account_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_sync_state(
        self, session: AsyncSession, account_id: int, folder: str
    ) -> SyncState:
        """Get existing sync state or create a new one for the folder."""
        stmt = select(SyncState).where(
            SyncState.account_id == account_id,
            SyncState.folder_name == folder,
        )
        result = await session.execute(stmt)
        state = result.scalar_one_or_none()

        if state is None:
            state = SyncState(
                account_id=account_id,
                folder_name=folder,
                last_synced_uid=0,
                status="idle",
            )
            session.add(state)
            await session.flush()

        return state

    async def _update_sync_state(
        self,
        session: AsyncSession,
        account_id: int,
        folder: str,
        uid: Optional[int] = None,
        status: Optional[str] = None,
    ) -> None:
        """Update the sync state record for a folder."""
        state = await self._get_or_create_sync_state(session, account_id, folder)

        if uid is not None:
            state.last_synced_uid = uid
        if status is not None:
            state.status = status
        state.last_synced_at = datetime.now(timezone.utc)

        await session.flush()

    async def _message_exists(
        self, session: AsyncSession, account_id: int, message_id: str
    ) -> bool:
        """Check if a message with the given message_id already exists for the account."""
        if not message_id:
            return False

        stmt = select(EmailMessage).where(
            EmailMessage.account_id == account_id,
            EmailMessage.message_id == message_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _persist_email(
        self,
        session: AsyncSession,
        account_id: int,
        uid: int,
        parsed: ParsedEmail,
    ) -> EmailMessage:
        """Persist a parsed email and its attachments to the database."""
        msg = EmailMessage(
            account_id=account_id,
            uid=uid,
            message_id=parsed.message_id,
            subject=parsed.subject,
            sender=parsed.sender,
            recipients=", ".join(parsed.recipients),
            date_received=parsed.date_received,
            body_text=parsed.body_text,
            body_html=parsed.body_html,
            has_attachments=parsed.has_attachments,
            is_read=parsed.is_read,
        )
        session.add(msg)
        await session.flush()

        for att in parsed.attachments:
            attachment = Attachment(
                message_id=msg.id,
                filename=att.filename,
                content_type=att.content_type,
                size_bytes=att.size_bytes,
                storage_path="",
            )
            session.add(attachment)

        return msg

    @staticmethod
    def _extract_uid_from_message(msg) -> Optional[int]:
        """Extract the IMAP UID from an email.message.Message object.

        The UID is typically stored in the IMAP FETCH response metadata.
        If not available, returns None.
        """
        uid_header = msg.get("X-UID")
        if uid_header:
            try:
                return int(uid_header)
            except (ValueError, TypeError):
                pass
        return None


from db.session import async_session_factory
