"""Tests for Pydantic request/response schemas."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from api.schemas import (
    AccountCreate,
    AccountResponse,
    AccountListResponse,
    SyncRequest,
    SyncResponse,
    AttachmentResponse,
    EmailResponse,
    EmailListResponse,
    EmailQueryParams,
)


class TestAccountCreate:
    """Tests for AccountCreate schema validation."""

    def test_valid_account_create(self):
        data = AccountCreate(
            user_id="test-user",
            email_address="test@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            username="test@example.com",
            password="secret",
        )
        assert data.user_id == "test-user"
        assert data.email_address == "test@example.com"
        assert data.imap_host == "imap.example.com"
        assert data.imap_port == 993
        assert data.password == "secret"

    def test_account_create_default_user_id(self):
        data = AccountCreate(
            email_address="test@example.com",
            imap_host="imap.example.com",
            username="test@example.com",
            password="secret",
        )
        assert data.user_id == "default"

    def test_account_create_default_port(self):
        data = AccountCreate(
            email_address="test@example.com",
            imap_host="imap.example.com",
            username="test@example.com",
            password="secret",
        )
        assert data.imap_port == 993

    def test_account_create_invalid_email(self):
        with pytest.raises(ValidationError):
            AccountCreate(
                email_address="not-an-email",
                imap_host="imap.example.com",
                username="user",
                password="secret",
            )

    def test_account_create_empty_imap_host(self):
        with pytest.raises(ValidationError):
            AccountCreate(
                email_address="test@example.com",
                imap_host="",
                username="user",
                password="secret",
            )

    def test_account_create_empty_username(self):
        with pytest.raises(ValidationError):
            AccountCreate(
                email_address="test@example.com",
                imap_host="imap.example.com",
                username="",
                password="secret",
            )

    def test_account_create_empty_password(self):
        with pytest.raises(ValidationError):
            AccountCreate(
                email_address="test@example.com",
                imap_host="imap.example.com",
                username="user",
                password="",
            )

    def test_account_create_invalid_port_too_low(self):
        with pytest.raises(ValidationError):
            AccountCreate(
                email_address="test@example.com",
                imap_host="imap.example.com",
                imap_port=0,
                username="user",
                password="secret",
            )

    def test_account_create_invalid_port_too_high(self):
        with pytest.raises(ValidationError):
            AccountCreate(
                email_address="test@example.com",
                imap_host="imap.example.com",
                imap_port=70000,
                username="user",
                password="secret",
            )

    def test_account_create_missing_required_fields(self):
        with pytest.raises(ValidationError):
            AccountCreate()


class TestAccountResponse:
    """Tests for AccountResponse schema."""

    def test_account_response_from_attributes(self):
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.user_id = "test-user"
        mock_account.email_address = "test@example.com"
        mock_account.imap_host = "imap.example.com"
        mock_account.imap_port = 993
        mock_account.username = "test@example.com"
        mock_account.is_active = True
        mock_account.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_account.updated_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        response = AccountResponse.model_validate(mock_account)
        assert response.id == 1
        assert response.email_address == "test@example.com"
        assert response.is_active is True


class TestAccountListResponse:
    """Tests for AccountListResponse schema."""

    def test_account_list_response(self):
        items = [
            AccountResponse(
                id=1,
                user_id="user1",
                email_address="a@example.com",
                imap_host="imap.example.com",
                imap_port=993,
                username="a@example.com",
                is_active=True,
                created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
                updated_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            ),
        ]
        response = AccountListResponse(items=items, total=1)
        assert len(response.items) == 1
        assert response.total == 1

    def test_account_list_response_empty(self):
        response = AccountListResponse(items=[], total=0)
        assert response.items == []
        assert response.total == 0


class TestSyncRequest:
    """Tests for SyncRequest schema."""

    def test_sync_request_with_folders(self):
        req = SyncRequest(folders=["INBOX", "Sent"])
        assert req.folders == ["INBOX", "Sent"]

    def test_sync_request_without_folders(self):
        req = SyncRequest()
        assert req.folders is None


class TestSyncResponse:
    """Tests for SyncResponse schema."""

    def test_sync_response(self):
        resp = SyncResponse(status="completed", messages_synced=42)
        assert resp.status == "completed"
        assert resp.messages_synced == 42


class TestAttachmentResponse:
    """Tests for AttachmentResponse schema."""

    def test_attachment_response(self):
        mock_att = MagicMock()
        mock_att.id = 1
        mock_att.filename = "report.pdf"
        mock_att.content_type = "application/pdf"
        mock_att.size_bytes = 1024
        mock_att.storage_path = "/tmp/report.pdf"

        response = AttachmentResponse.model_validate(mock_att)
        assert response.id == 1
        assert response.filename == "report.pdf"
        assert response.content_type == "application/pdf"
        assert response.size_bytes == 1024


class TestEmailResponse:
    """Tests for EmailResponse schema."""

    def test_email_response_from_attributes(self):
        mock_email = MagicMock()
        mock_email.id = 1
        mock_email.account_id = 1
        mock_email.uid = 100
        mock_email.message_id = "<msg@example.com>"
        mock_email.subject = "Test Subject"
        mock_email.sender = "sender@example.com"
        mock_email.recipients = "recipient@example.com"
        mock_email.date_received = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_email.body_text = "Body text"
        mock_email.body_html = "<p>HTML</p>"
        mock_email.has_attachments = False
        mock_email.is_read = False
        mock_email.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        response = EmailResponse.model_validate(mock_email)
        assert response.id == 1
        assert response.subject == "Test Subject"
        assert response.attachments == []

    def test_email_response_with_attachments(self):
        mock_email = MagicMock()
        mock_email.id = 1
        mock_email.account_id = 1
        mock_email.uid = 100
        mock_email.message_id = "<msg@example.com>"
        mock_email.subject = "Test"
        mock_email.sender = "sender@example.com"
        mock_email.recipients = "recipient@example.com"
        mock_email.date_received = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_email.body_text = "Body"
        mock_email.body_html = ""
        mock_email.has_attachments = True
        mock_email.is_read = False
        mock_email.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        mock_att = MagicMock()
        mock_att.id = 1
        mock_att.filename = "file.pdf"
        mock_att.content_type = "application/pdf"
        mock_att.size_bytes = 512
        mock_att.storage_path = "/tmp/file.pdf"

        response = EmailResponse.model_validate(mock_email)
        response.attachments = [AttachmentResponse.model_validate(mock_att)]

        assert response.has_attachments is True
        assert len(response.attachments) == 1
        assert response.attachments[0].filename == "file.pdf"

    def test_email_response_optional_subject(self):
        mock_email = MagicMock()
        mock_email.id = 1
        mock_email.account_id = 1
        mock_email.uid = 100
        mock_email.message_id = "<msg@example.com>"
        mock_email.subject = None
        mock_email.sender = "sender@example.com"
        mock_email.recipients = "recipient@example.com"
        mock_email.date_received = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_email.body_text = "Body"
        mock_email.body_html = ""
        mock_email.has_attachments = False
        mock_email.is_read = False
        mock_email.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        response = EmailResponse.model_validate(mock_email)
        assert response.subject is None


class TestEmailListResponse:
    """Tests for EmailListResponse schema."""

    def test_email_list_response(self):
        mock_email = MagicMock()
        mock_email.id = 1
        mock_email.account_id = 1
        mock_email.uid = 100
        mock_email.message_id = "<msg@example.com>"
        mock_email.subject = "Test"
        mock_email.sender = "sender@example.com"
        mock_email.recipients = "recipient@example.com"
        mock_email.date_received = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mock_email.body_text = "Body"
        mock_email.body_html = ""
        mock_email.has_attachments = False
        mock_email.is_read = False
        mock_email.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        items = [EmailResponse.model_validate(mock_email)]
        response = EmailListResponse(items=items, total=1)
        assert response.total == 1
        assert len(response.items) == 1


class TestEmailQueryParams:
    """Tests for EmailQueryParams schema."""

    def test_default_values(self):
        params = EmailQueryParams()
        assert params.account_id is None
        assert params.limit == 50
        assert params.offset == 0
        assert params.search is None
        assert params.is_read is None
        assert params.has_attachments is None

    def test_custom_values(self):
        params = EmailQueryParams(
            account_id=1,
            limit=10,
            offset=20,
            search="invoice",
            is_read=True,
            has_attachments=False,
        )
        assert params.account_id == 1
        assert params.limit == 10
        assert params.offset == 20
        assert params.search == "invoice"
        assert params.is_read is True
        assert params.has_attachments is False

    def test_limit_validation_too_low(self):
        with pytest.raises(ValidationError):
            EmailQueryParams(limit=0)

    def test_limit_validation_too_high(self):
        with pytest.raises(ValidationError):
            EmailQueryParams(limit=201)

    def test_offset_validation_negative(self):
        with pytest.raises(ValidationError):
            EmailQueryParams(offset=-1)
