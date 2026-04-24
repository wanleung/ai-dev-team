"""SQLAlchemy ORM models for the MCP Email Service."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin


class EmailAccount(TimestampMixin, Base):
    """Stores IMAP account credentials and connection details."""

    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email_address: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # OAuth2 fields
    auth_method: Mapped[str] = mapped_column(String(20), default="basic", nullable=False)
    oauth2_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth2_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth2_client_secret: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    oauth2_access_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    oauth2_refresh_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    oauth2_token_expiry: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    oauth2_scopes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    messages: Mapped[list["EmailMessage"]] = relationship(
        "EmailMessage", back_populates="account", cascade="all, delete-orphan"
    )
    sync_states: Mapped[list["SyncState"]] = relationship(
        "SyncState", back_populates="account", cascade="all, delete-orphan"
    )


class EmailMessage(TimestampMixin, Base):
    """Stores parsed and normalised email metadata."""

    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uid: Mapped[int] = mapped_column(Integer, nullable=False)
    message_id: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(1024), nullable=True)
    sender: Mapped[str] = mapped_column(String(1024), nullable=False)
    recipients: Mapped[str] = mapped_column(Text, nullable=False)
    date_received: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=True)
    body_html: Mapped[str] = mapped_column(Text, nullable=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    account: Mapped["EmailAccount"] = relationship("EmailAccount", back_populates="messages")
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment", back_populates="message", cascade="all, delete-orphan"
    )


class SyncState(TimestampMixin, Base):
    """Tracks IMAP UID sync progress per account and folder."""

    __tablename__ = "sync_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("email_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    folder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_synced_uid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_synced_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="idle", nullable=False)

    account: Mapped["EmailAccount"] = relationship("EmailAccount", back_populates="sync_states")


class Attachment(TimestampMixin, Base):
    """Stores metadata for email attachments."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(2048), nullable=False)

    message: Mapped["EmailMessage"] = relationship("EmailMessage", back_populates="attachments")
