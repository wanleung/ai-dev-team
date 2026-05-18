"""Pydantic request/response schemas for the REST API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# --- Account Schemas ---

class AccountCreate(BaseModel):
    """Request body for registering a new IMAP account."""

    user_id: str = Field(default="default", description="User identifier for multi-tenant support")
    email_address: EmailStr = Field(..., description="Email address for the IMAP account")
    imap_host: str = Field(..., min_length=1, description="IMAP server hostname")
    imap_port: int = Field(default=993, ge=1, le=65535, description="IMAP server port")
    username: str = Field(..., min_length=1, description="IMAP username for authentication")
    password: str = Field(..., min_length=1, description="IMAP password or OAuth2 token")


class AccountResponse(BaseModel):
    """Response body for a registered account."""

    id: int
    user_id: str
    email_address: str
    imap_host: str
    imap_port: int
    username: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountListResponse(BaseModel):
    """Response body for listing registered accounts."""

    items: list[AccountResponse]
    total: int


class SyncRequest(BaseModel):
    """Request body for triggering an incremental sync."""

    folders: Optional[list[str]] = Field(
        default=None,
        description="List of folders to sync. If None, syncs all folders.",
    )


class SyncResponse(BaseModel):
    """Response body for a sync operation."""

    status: str
    messages_synced: int


# --- Email Schemas ---

class AttachmentResponse(BaseModel):
    """Response body for an email attachment."""

    id: int
    filename: str
    content_type: str
    size_bytes: int
    storage_path: str

    model_config = {"from_attributes": True}


class EmailResponse(BaseModel):
    """Response body for a single cached email."""

    id: int
    account_id: int
    uid: int
    message_id: str
    subject: Optional[str]
    sender: str
    recipients: str
    date_received: datetime
    body_text: Optional[str]
    body_html: Optional[str]
    has_attachments: bool
    is_read: bool
    created_at: datetime
    attachments: list[AttachmentResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class EmailListResponse(BaseModel):
    """Response body for listing cached emails."""

    items: list[EmailResponse]
    total: int


# --- Query Parameters ---

class EmailQueryParams(BaseModel):
    """Query parameters for filtering cached emails."""

    account_id: Optional[int] = Field(default=None, description="Filter by account ID")
    limit: int = Field(default=50, ge=1, le=200, description="Number of results per page")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")
    search: Optional[str] = Field(default=None, description="Search term for subject/sender")
    is_read: Optional[bool] = Field(default=None, description="Filter by read status")
    has_attachments: Optional[bool] = Field(
        default=None, description="Filter by attachment presence",
    )
