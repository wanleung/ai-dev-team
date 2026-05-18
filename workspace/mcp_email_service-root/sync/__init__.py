"""Sync & Cache Manager for MCP Email Service.

Implements UID tracking, incremental fetch scheduler, deduplication,
and background task runner for email synchronization.
"""

from sync.manager import SyncManager

__all__ = ["SyncManager"]
