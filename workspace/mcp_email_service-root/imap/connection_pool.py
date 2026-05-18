"""Connection pool management for IMAP clients.

Provides a pool of reusable IMAP connections to avoid the overhead
of repeated connect/disconnect cycles for multiple accounts.
"""

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from imap.client import IMAPClient
from imap.oauth2_manager import OAuth2Manager

logger = logging.getLogger(__name__)


class IMAPConnectionPool:
    """Manages a pool of IMAP connections per account.

    Maintains active connections for multiple email accounts,
    reusing them for subsequent operations to reduce latency.

    Attributes:
        max_connections_per_account: Maximum concurrent connections per account
        idle_timeout: Seconds before an idle connection is closed
        health_check_interval: Seconds between connection health checks
        oauth2_manager: Optional OAuth2 manager for token refresh
    """

    def __init__(
        self,
        max_connections_per_account: int = 3,
        idle_timeout: float = 300.0,
        health_check_interval: float = 60.0,
        oauth2_manager: OAuth2Manager | None = None,
    ) -> None:
        """Initialize the connection pool with configuration.

        Args:
            max_connections_per_account: Maximum connections per account
            idle_timeout: Seconds before idle connections are closed
            health_check_interval: Seconds between health check runs
            oauth2_manager: Optional OAuth2 manager for automatic token refresh
        """
        self.max_connections_per_account = max_connections_per_account
        self.idle_timeout = idle_timeout
        self.health_check_interval = health_check_interval
        self.oauth2_manager = oauth2_manager

        self._pool: dict[int, list[tuple[IMAPClient, float]]] = defaultdict(list)
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._health_check_task: asyncio.Task | None = None
        self._running = False

        self._account_config: dict[int, dict] = {}

    def register_account(
        self,
        account_id: int,
        host: str,
        port: int,
        username: str,
        password: str,
        use_oauth: bool = False,
    ) -> None:
        """Register account connection parameters for later use.

        Args:
            account_id: Unique identifier for the email account
            host: IMAP server hostname
            port: IMAP server port
            username: Account username
            password: Account password or OAuth2 token
            use_oauth: Whether to use OAuth2 authentication
        """
        self._account_config[account_id] = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "use_oauth": use_oauth,
        }

    async def start(self) -> None:
        """Start the connection pool and health check background task."""
        self._running = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("IMAP connection pool started")

    async def stop(self) -> None:
        """Stop the connection pool and close all connections."""
        self._running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        for account_id in list(self._pool.keys()):
            await self._close_all_for_account(account_id)

        self._pool.clear()
        self._locks.clear()
        self._account_config.clear()
        logger.info("IMAP connection pool stopped")

    async def get_connection(
        self,
        account_id: int,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        use_oauth: bool | None = None,
    ) -> IMAPClient:
        """Get an IMAP connection from the pool or create a new one.

        If parameters are not provided, they are looked up from registered
        account configuration.

        Args:
            account_id: Unique identifier for the email account
            host: IMAP server hostname (or from registered config)
            port: IMAP server port (or from registered config)
            username: Account username (or from registered config)
            password: Account password or OAuth2 token (or from registered config)
            use_oauth: Whether to use OAuth2 authentication (or from registered config)

        Returns:
            An IMAPClient instance ready for use

        Raises:
            ValueError: If account parameters are not provided or registered
        """
        config = self._resolve_config(
            account_id, host, port, username, password, use_oauth
        )

        oauth2_callback = None
        if config["use_oauth"] and self.oauth2_manager:
            oauth2_callback = lambda aid=account_id: self.oauth2_manager.get_access_token(aid)

        async with self._locks[account_id]:
            pool = self._pool[account_id]
            for i, (client, last_used) in enumerate(pool):
                if client.is_connected:
                    pool.pop(i)
                    return client
                else:
                    await client.disconnect()

            if len(pool) < self.max_connections_per_account:
                client = IMAPClient(
                    host=config["host"],
                    port=config["port"],
                    username=config["username"],
                    password=config["password"],
                    use_oauth=config["use_oauth"],
                    oauth2_token_callback=oauth2_callback,
                )
                await client.connect()
                return client

            logger.warning(
                f"Connection pool full for account {account_id}, waiting for available connection"
            )
            client, _ = pool.pop(0)
            if not client.is_connected:
                await client.disconnect()
                client = IMAPClient(
                    host=config["host"],
                    port=config["port"],
                    username=config["username"],
                    password=config["password"],
                    use_oauth=config["use_oauth"],
                    oauth2_token_callback=oauth2_callback,
                )
                await client.connect()
            return client

    async def return_connection(self, account_id: int, client: IMAPClient) -> None:
        """Return a connection to the pool for reuse.

        Args:
            account_id: Account identifier for the connection
            client: IMAPClient instance to return to pool
        """
        async with self._locks[account_id]:
            if client.is_connected:
                self._pool[account_id].append((client, time.time()))
            else:
                await client.disconnect()

    @asynccontextmanager
    async def connection(
        self,
        account_id: int,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        use_oauth: bool | None = None,
    ) -> AsyncGenerator[IMAPClient, None]:
        """Context manager for acquiring and returning IMAP connections.

        Automatically returns the connection to the pool when the context exits.

        Args:
            account_id: Unique identifier for the email account
            host: IMAP server hostname (or from registered config)
            port: IMAP server port (or from registered config)
            username: Account username (or from registered config)
            password: Account password or OAuth2 token (or from registered config)
            use_oauth: Whether to use OAuth2 authentication (or from registered config)

        Yields:
            An IMAPClient instance ready for use
        """
        client = await self.get_connection(
            account_id, host, port, username, password, use_oauth
        )
        try:
            yield client
        finally:
            await self.return_connection(account_id, client)

    async def _health_check_loop(self) -> None:
        """Background task that periodically checks and cleans up connections."""
        while self._running:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._cleanup_idle_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    async def _cleanup_idle_connections(self) -> None:
        """Remove connections that have been idle too long."""
        current_time = time.time()

        for account_id in list(self._pool.keys()):
            async with self._locks[account_id]:
                pool = self._pool[account_id]
                valid_connections = []

                for client, last_used in pool:
                    idle_time = current_time - last_used
                    if idle_time > self.idle_timeout or not client.is_connected:
                        await client.disconnect()
                    else:
                        valid_connections.append((client, last_used))

                self._pool[account_id] = valid_connections

    async def _close_all_for_account(self, account_id: int) -> None:
        """Close all connections for a specific account.

        Args:
            account_id: Account identifier to close connections for
        """
        async with self._locks[account_id]:
            pool = self._pool[account_id]
            for client, _ in pool:
                await client.disconnect()
            pool.clear()

    async def close_account_connections(self, account_id: int) -> None:
        """Public method to close all connections for an account.

        Use this when an account is deactivated or removed.

        Args:
            account_id: Account identifier to close connections for
        """
        await self._close_all_for_account(account_id)
        if account_id in self._locks:
            del self._locks[account_id]
        if account_id in self._account_config:
            del self._account_config[account_id]
        if self.oauth2_manager:
            self.oauth2_manager.remove_token(account_id)

    def get_pool_stats(self) -> dict[int, int]:
        """Get current pool statistics.

        Returns:
            Dictionary mapping account_id to number of pooled connections
        """
        return {
            account_id: len(connections)
            for account_id, connections in self._pool.items()
        }

    def _resolve_config(
        self,
        account_id: int,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        use_oauth: bool | None = None,
    ) -> dict:
        """Resolve account configuration from parameters or registered config.

        Args:
            account_id: Account identifier
            host: Optional host override
            port: Optional port override
            username: Optional username override
            password: Optional password override
            use_oauth: Optional use_oauth override

        Returns:
            Dictionary with resolved connection parameters

        Raises:
            ValueError: If required parameters are missing
        """
        if account_id in self._account_config:
            config = self._account_config[account_id].copy()
            if host is not None:
                config["host"] = host
            if port is not None:
                config["port"] = port
            if username is not None:
                config["username"] = username
            if password is not None:
                config["password"] = password
            if use_oauth is not None:
                config["use_oauth"] = use_oauth
            return config

        if all([host, username, password]):
            return {
                "host": host,
                "port": port or 993,
                "username": username,
                "password": password,
                "use_oauth": use_oauth or False,
            }

        raise ValueError(
            f"No configuration available for account {account_id}. "
            "Register the account or provide connection parameters."
        )
