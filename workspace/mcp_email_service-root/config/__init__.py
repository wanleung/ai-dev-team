"""Secure configuration layer for MCP Email Service.

Provides environment variable loading, secret management,
and secure configuration for database credentials and encryption keys.
"""

from config.settings import Settings, get_settings, get_encryption_manager

__all__ = ["Settings", "get_settings", "get_encryption_manager"]
