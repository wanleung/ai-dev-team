"""Secure configuration layer for MCP Email Service.

Handles environment variable loading, secret management,
password encryption/decryption, and database credential management.
"""

import os
from base64 import urlsafe_b64encode
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EncryptionManager:
    """Manages symmetric encryption for sensitive credentials.

    Uses Fernet (AES-128-CBC) for encrypting/decrypting passwords
    and other secrets stored in the database.
    """

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string and return base64-encoded ciphertext.

        Args:
            plaintext: The secret string to encrypt.

        Returns:
            Base64-encoded encrypted string.
        """
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a base64-encoded ciphertext string.

        Args:
            ciphertext: The base64-encoded encrypted string.

        Returns:
            The decrypted plaintext string.

        Raises:
            cryptography.fernet.InvalidToken: If the ciphertext is invalid.
        """
        return self._fernet.decrypt(ciphertext.encode()).decode()

    @classmethod
    def generate_key(cls) -> bytes:
        """Generate a new Fernet encryption key.

        Returns:
            A 32-byte URL-safe base64-encoded key.
        """
        return Fernet.generate_key()

    @classmethod
    def key_from_secret(cls, secret: str) -> bytes:
        """Derive a Fernet key from a secret string.

        The secret is hashed to 32 bytes and URL-safe base64 encoded
        to produce a valid Fernet key.

        Args:
            secret: The secret string to derive a key from.

        Returns:
            A valid Fernet key bytes.
        """
        import hashlib

        key_bytes = hashlib.sha256(secret.encode()).digest()
        return urlsafe_b64encode(key_bytes)


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file.

    All sensitive values are wrapped in SecretStr to prevent accidental logging.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="MCP Email Service", description="Application name")
    debug: bool = Field(default=False, description="Debug mode flag")
    secret_key: SecretStr = Field(
        default=SecretStr("change-me-in-production"),
        description="Application secret key for sessions and tokens",
    )
    allowed_hosts: list[str] = Field(
        default=["*"], description="Allowed HTTP hosts"
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/mcp_email",
        description="Database connection URL (PostgreSQL or SQLite)",
    )
    db_pool_size: int = Field(default=20, description="Database connection pool size")
    db_max_overflow: int = Field(
        default=10, description="Database pool max overflow"
    )
    db_echo: bool = Field(default=False, description="Echo SQL statements")

    @property
    def is_sqlite(self) -> bool:
        """Check if the database URL indicates SQLite."""
        return "sqlite" in self.database_url

    # Encryption
    encryption_key: Optional[str] = Field(
        default=None,
        description="Fernet encryption key for password encryption. "
        "If not provided, derived from SECRET_KEY.",
    )

    # IMAP Defaults
    default_imap_port: int = Field(default=993, description="Default IMAP SSL port")
    imap_connection_timeout: int = Field(
        default=30, description="IMAP connection timeout in seconds"
    )
    imap_max_retries: int = Field(default=3, description="Max IMAP connection retries")
    imap_retry_delay: float = Field(
        default=1.0, description="Delay between IMAP retries in seconds"
    )

    # Sync
    sync_interval_seconds: int = Field(
        default=300, description="Background sync interval in seconds"
    )
    sync_batch_size: int = Field(
        default=100, description="Number of messages to sync per batch"
    )

    # MCP Server
    mcp_transport: str = Field(
        default="stdio", description="MCP transport: stdio or sse"
    )
    mcp_server_host: str = Field(default="0.0.0.0", description="MCP SSE host")
    mcp_server_port: int = Field(default=8000, description="MCP SSE port")

    # REST API
    api_prefix: str = Field(default="/api", description="API URL prefix")
    cors_origins: list[str] = Field(
        default=["*"], description="CORS allowed origins"
    )

    # File Storage
    attachment_storage_path: str = Field(
        default="./attachments", description="Local path for attachment storage"
    )
    max_attachment_size_mb: int = Field(
        default=25, description="Max attachment size in MB"
    )

    @field_validator("encryption_key", mode="before")
    @classmethod
    def derive_encryption_key(cls, v: Optional[str], info) -> Optional[str]:
        """Derive encryption key from secret_key if not explicitly provided."""
        if v is not None:
            return v
        secret_key = info.data.get("secret_key")
        if isinstance(secret_key, SecretStr):
            secret_key = secret_key.get_secret_value()
        if secret_key and secret_key != "change-me-in-production":
            return EncryptionManager.key_from_secret(secret_key).decode()
        return None

    def get_encryption_manager(self) -> EncryptionManager:
        """Create an EncryptionManager instance from current settings.

        Returns:
            Configured EncryptionManager ready for encrypt/decrypt operations.

        Raises:
            ValueError: If no valid encryption key is configured.
        """
        key = self.encryption_key
        if key is None:
            if self.debug:
                key = EncryptionManager.generate_key().decode()
            else:
                raise ValueError(
                    "ENCRYPTION_KEY must be set in production. "
                    "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                )

        key_bytes = key.encode() if isinstance(key, str) else key
        return EncryptionManager(key_bytes)

    @property
    def database_url_sync(self) -> str:
        """Return synchronous database URL for Alembic migrations.

        Converts asyncpg driver to psycopg2 for sync operations.
        """
        url = str(self.database_url)
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    def ensure_storage_path(self) -> Path:
        """Ensure the attachment storage directory exists.

        Returns:
            Path object for the attachment storage directory.
        """
        path = Path(self.attachment_storage_path)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings singleton.

    Returns:
        Settings instance loaded from environment.
    """
    return Settings()


def get_encryption_manager() -> EncryptionManager:
    """Get an EncryptionManager configured from current settings.

    Returns:
        Configured EncryptionManager instance.
    """
    return get_settings().get_encryption_manager()
