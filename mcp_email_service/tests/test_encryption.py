"""Tests for EncryptionManager and Settings."""

import os
from unittest.mock import patch, MagicMock

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from config.settings import EncryptionManager, Settings, get_settings, get_encryption_manager


class TestEncryptionManager:
    """Tests for the EncryptionManager class."""

    def test_encrypt_and_decrypt_roundtrip(self, encryption_manager):
        plaintext = "my-secret-password"
        encrypted = encryption_manager.encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertext_each_time(self, encryption_manager):
        plaintext = "same-password"
        encrypted1 = encryption_manager.encrypt(plaintext)
        encrypted2 = encryption_manager.encrypt(plaintext)
        assert encrypted1 != encrypted2

    def test_decrypt_with_invalid_ciphertext_raises(self, encryption_manager):
        with pytest.raises(InvalidToken):
            encryption_manager.decrypt("not-a-valid-token")

    def test_decrypt_with_tampered_ciphertext_raises(self, encryption_manager):
        encrypted = encryption_manager.encrypt("secret")
        tampered = encrypted[:-1] + ("A" if encrypted[-1] != "A" else "B")
        with pytest.raises(InvalidToken):
            encryption_manager.decrypt(tampered)

    def test_generate_key_returns_valid_fernet_key(self):
        key = EncryptionManager.generate_key()
        Fernet(key)

    def test_key_from_secret_produces_valid_key(self):
        secret = "my-app-secret"
        key = EncryptionManager.key_from_secret(secret)
        Fernet(key)

    def test_key_from_secret_is_deterministic(self):
        secret = "consistent-secret"
        key1 = EncryptionManager.key_from_secret(secret)
        key2 = EncryptionManager.key_from_secret(secret)
        assert key1 == key2

    def test_key_from_secret_different_for_different_secrets(self):
        key1 = EncryptionManager.key_from_secret("secret-a")
        key2 = EncryptionManager.key_from_secret("secret-b")
        assert key1 != key2

    def test_encrypt_empty_string(self, encryption_manager):
        encrypted = encryption_manager.encrypt("")
        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == ""

    def test_encrypt_unicode_string(self, encryption_manager):
        plaintext = "密码测试🔒"
        encrypted = encryption_manager.encrypt(plaintext)
        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_long_string(self, encryption_manager):
        plaintext = "x" * 10000
        encrypted = encryption_manager.encrypt(plaintext)
        decrypted = encryption_manager.decrypt(encrypted)
        assert decrypted == plaintext


class TestSettings:
    """Tests for the Settings class."""

    def test_default_settings_values(self):
        with patch("config.settings.Settings.model_config", {}):
            with patch.dict(os.environ, {"ENCRYPTION_KEY": Fernet.generate_key().decode()}):
                settings = Settings()
                assert settings.app_name == "MCP Email Service"
                assert settings.debug is False
                assert settings.default_imap_port == 993
                assert settings.sync_batch_size == 100
                assert settings.mcp_transport == "stdio"

    def test_get_encryption_manager_with_explicit_key(self):
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": key}):
            settings = Settings()
            manager = settings.get_encryption_manager()
            assert isinstance(manager, EncryptionManager)
            encrypted = manager.encrypt("test")
            assert manager.decrypt(encrypted) == "test"

    def test_get_encryption_manager_in_debug_mode_generates_key(self):
        with patch.dict(os.environ, {
            "DEBUG": "true",
            "ENCRYPTION_KEY": "",
        }, clear=False):
            settings = Settings()
            manager = settings.get_encryption_manager()
            assert isinstance(manager, EncryptionManager)

    def test_get_encryption_manager_raises_in_production_without_key(self):
        with patch.dict(os.environ, {
            "DEBUG": "false",
            "ENCRYPTION_KEY": "",
            "SECRET_KEY": "change-me-in-production",
        }, clear=False):
            settings = Settings()
            with pytest.raises(ValueError, match="ENCRYPTION_KEY must be set"):
                settings.get_encryption_manager()

    def test_database_url_sync_converts_driver(self):
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db",
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }):
            settings = Settings()
            assert "postgresql+psycopg2://" in settings.database_url_sync
            assert "asyncpg" not in settings.database_url_sync

    def test_ensure_storage_path_creates_directory(self, tmp_path):
        storage_path = str(tmp_path / "attachments")
        with patch.dict(os.environ, {
            "ATTACHMENT_STORAGE_PATH": storage_path,
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }):
            settings = Settings()
            path = settings.ensure_storage_path()
            assert path.exists()
            assert path.is_dir()

    def test_settings_from_environment_variables(self):
        with patch.dict(os.environ, {
            "APP_NAME": "Custom App",
            "DEBUG": "true",
            "SYNC_INTERVAL_SECONDS": "600",
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }):
            settings = Settings()
            assert settings.app_name == "Custom App"
            assert settings.debug is True
            assert settings.sync_interval_seconds == 600

    def test_secret_key_not_logged(self):
        with patch.dict(os.environ, {
            "SECRET_KEY": "super-secret-key-123",
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }):
            settings = Settings()
            assert isinstance(settings.secret_key, SecretStr)
            repr_str = repr(settings.secret_key)
            assert "super-secret-key-123" not in repr_str


class TestGetSettings:
    """Tests for settings helper functions."""

    def test_get_settings_returns_cached_instance(self):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": Fernet.generate_key().decode()}):
            get_settings.cache_clear()
            s1 = get_settings()
            s2 = get_settings()
            assert s1 is s2
            get_settings.cache_clear()

    def test_get_encryption_manager_returns_manager(self):
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": key}):
            get_settings.cache_clear()
            manager = get_encryption_manager()
            assert isinstance(manager, EncryptionManager)
            get_settings.cache_clear()
