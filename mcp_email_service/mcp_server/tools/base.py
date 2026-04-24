"""Shared helpers and dependency injection for MCP tools."""

import logging
from typing import Optional

from imap.connection_pool import IMAPConnectionPool
from imap.oauth2_manager import OAuth2Manager
from sync.manager import SyncManager

logger = logging.getLogger(__name__)

_deps: "AppDependencies | None" = None


class AppDependencies:
    """Holds all application dependencies injected via lifespan.

    Attributes:
        sync_manager: The sync manager for email synchronization
        connection_pool: The IMAP connection pool
        oauth2_manager: Optional OAuth2 manager for token refresh
    """

    def __init__(
        self,
        sync_manager: SyncManager,
        connection_pool: IMAPConnectionPool,
        oauth2_manager: Optional[OAuth2Manager] = None,
    ) -> None:
        """Initialize application dependencies.

        Args:
            sync_manager: The sync manager for email synchronization
            connection_pool: The IMAP connection pool
            oauth2_manager: Optional OAuth2 manager for token refresh
        """
        self.sync_manager = sync_manager
        self.connection_pool = connection_pool
        self.oauth2_manager = oauth2_manager


def set_dependencies(deps: AppDependencies) -> None:
    """Set the application dependencies for all registered tools.

    Called by the server lifespan after initializing all services.

    Args:
        deps: Application dependencies with fully initialized services.
    """
    global _deps
    _deps = deps


def _require_deps() -> AppDependencies:
    """Return the current dependencies or raise if not initialized."""
    if _deps is None:
        raise RuntimeError("Application dependencies not initialized. Call set_dependencies() first.")
    return _deps
