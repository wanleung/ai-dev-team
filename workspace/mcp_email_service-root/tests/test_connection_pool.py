"""Tests for IMAPConnectionPool."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from imap.connection_pool import IMAPConnectionPool


class TestIMAPConnectionPoolInit:
    """Tests for IMAPConnectionPool initialization."""

    def test_default_values(self):
        pool = IMAPConnectionPool()
        assert pool.max_connections_per_account == 3
        assert pool.idle_timeout == 300.0
        assert pool.health_check_interval == 60.0

    def test_custom_values(self):
        pool = IMAPConnectionPool(
            max_connections_per_account=5,
            idle_timeout=60.0,
            health_check_interval=30.0,
        )
        assert pool.max_connections_per_account == 5
        assert pool.idle_timeout == 60.0
        assert pool.health_check_interval == 30.0


class TestIMAPConnectionPoolStartStop:
    """Tests for pool start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_health_check_task(self):
        pool = IMAPConnectionPool(health_check_interval=0.1)
        await pool.start()
        assert pool._running is True
        assert pool._health_check_task is not None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self):
        pool = IMAPConnectionPool(health_check_interval=0.1)
        await pool.start()
        await pool.stop()
        assert pool._running is False


class TestIMAPConnectionPoolGetConnection:
    """Tests for get_connection."""

    @pytest.mark.asyncio
    async def test_get_connection_creates_new_when_pool_empty(self):
        pool = IMAPConnectionPool()

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()

        with patch("imap.connection_pool.IMAPClient", return_value=mock_client):
            client = await pool.get_connection(
                account_id=1,
                host="imap.example.com",
                port=993,
                username="user",
                password="pass",
            )
            assert client is mock_client
            mock_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_reuses_from_pool(self):
        pool = IMAPConnectionPool()

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()

        with patch("imap.connection_pool.IMAPClient", return_value=mock_client):
            client1 = await pool.get_connection(
                account_id=1, host="imap.example.com", port=993,
                username="user", password="pass",
            )
            await pool.return_connection(1, client1)

            client2 = await pool.get_connection(
                account_id=1, host="imap.example.com", port=993,
                username="user", password="pass",
            )
            assert client2 is client1


class TestIMAPConnectionPoolReturnConnection:
    """Tests for return_connection."""

    @pytest.mark.asyncio
    async def test_return_connection_adds_to_pool(self):
        pool = IMAPConnectionPool()

        mock_client = MagicMock()
        mock_client.is_connected = True

        await pool.return_connection(1, mock_client)
        assert len(pool._pool[1]) == 1

    @pytest.mark.asyncio
    async def test_return_connection_disconnects_dead_connection(self):
        pool = IMAPConnectionPool()

        mock_client = MagicMock()
        mock_client.is_connected = False
        mock_client.disconnect = AsyncMock()

        await pool.return_connection(1, mock_client)
        mock_client.disconnect.assert_called_once()
        assert len(pool._pool[1]) == 0


class TestIMAPConnectionPoolContextManager:
    """Tests for connection() context manager."""

    @pytest.mark.asyncio
    async def test_connection_yields_and_returns(self):
        pool = IMAPConnectionPool()

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()

        with patch("imap.connection_pool.IMAPClient", return_value=mock_client):
            async with pool.connection(
                account_id=1, host="imap.example.com", port=993,
                username="user", password="pass",
            ) as client:
                assert client is mock_client

            assert len(pool._pool[1]) == 1


class TestIMAPConnectionPoolHealthCheck:
    """Tests for health check loop."""

    @pytest.mark.asyncio
    async def test_cleanup_idle_connections(self):
        pool = IMAPConnectionPool(idle_timeout=0.01)

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.disconnect = AsyncMock()

        import time
        pool._pool[1].append((mock_client, time.time() - 100))

        await pool._cleanup_idle_connections()
        mock_client.disconnect.assert_called_once()


class TestIMAPConnectionPoolCloseAccount:
    """Tests for close_account_connections."""

    @pytest.mark.asyncio
    async def test_close_account_connections(self):
        pool = IMAPConnectionPool()

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.disconnect = AsyncMock()

        pool._pool[1].append((mock_client, 0))

        await pool.close_account_connections(1)
        mock_client.disconnect.assert_called_once()
        assert 1 not in pool._locks


class TestIMAPConnectionPoolStats:
    """Tests for get_pool_stats."""

    def test_get_pool_stats_empty(self):
        pool = IMAPConnectionPool()
        assert pool.get_pool_stats() == {}

    def test_get_pool_stats_with_connections(self):
        pool = IMAPConnectionPool()

        mock_client1 = MagicMock()
        mock_client2 = MagicMock()

        pool._pool[1].append((mock_client1, 0))
        pool._pool[1].append((mock_client2, 0))
        pool._pool[2].append((mock_client1, 0))

        stats = pool.get_pool_stats()
        assert stats[1] == 2
        assert stats[2] == 1
