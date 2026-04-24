"""Tests for EmailParser."""

import email
from email.message import Message
from email.header import Header

import pytest

from parser.email_parser import EmailParser, ParsedEmail, AttachmentInfo


class TestEmailParser:
    """Tests for the EmailParser class."""

    def test_parse_raw_bytes_plain_text(self, sample_raw_email):
        parser = EmailParser()
        parsed = parser.parse_raw_bytes(sample_raw_email)

        assert isinstance(parsed, ParsedEmail)
        assert parsed.sender == "sender@example.com"
        assert parsed.sender_email == "sender@example.com"
        assert parsed.recipients == ["recipient@example.com"]
        assert parsed.recipients_raw == "recipient@example.com"
        assert parsed.subject == "Test Email"
        assert parsed.message_id == "<test123@example.com>"
        assert "plain text body" in parsed.body_text
        assert parsed.body_html == ""
        assert parsed.has_attachments is False
        assert len(parsed.attachments) == 0

    def test_parse_raw_bytes_multipart(self, sample_raw_email_multipart):
        parser = EmailParser()
        parsed = parser.parse_raw_bytes(sample_raw_email_multipart)

        assert parsed.subject == "Multipart Test Email"
        assert "Plain text body" in parsed.body_text
        assert "<html>" in parsed.body_html
        assert parsed.has_attachments is True
        assert len(parsed.attachments) == 1
        assert parsed.attachments[0].filename == "report.pdf"
        assert parsed.attachments[0].content_type == "application/pdf"

    def test_parse_raw_bytes_html_only(self, sample_raw_email_html_only):
        parser = EmailParser()
        parsed = parser.parse_raw_bytes(sample_raw_email_html_only)

        assert parsed.subject == "HTML Only Email"
        assert parsed.body_text == ""
        assert "<html>" in parsed.body_html
        assert parsed.has_attachments is False

    def test_parse_message_directly(self, sample_raw_email):
        msg = email.message_from_bytes(sample_raw_email)
        parser = EmailParser()
        parsed = parser.parse_message(msg)

        assert parsed.sender_email == "sender@example.com"
        assert parsed.subject == "Test Email"

    def test_parse_raw_bytes_invalid_raises(self):
        parser = EmailParser()
        with pytest.raises(ValueError, match="Failed to parse"):
            parser.parse_raw_bytes(b"")

    def test_html_sanitization_removes_script_tags(self, sample_raw_email_with_dangerous_html):
        parser = EmailParser(sanitize_html=True)
        parsed = parser.parse_raw_bytes(sample_raw_email_with_dangerous_html)

        assert "<script>" not in parsed.body_html
        assert "alert" not in parsed.body_html
        assert "Safe content" in parsed.body_html

    def test_html_sanitization_removes_event_handlers(self, sample_raw_email_with_dangerous_html):
        parser = EmailParser(sanitize_html=True)
        parsed = parser.parse_raw_bytes(sample_raw_email_with_dangerous_html)

        assert "onclick" not in parsed.body_html

    def test_html_sanitization_removes_javascript_urls(self, sample_raw_email_with_dangerous_html):
        parser = EmailParser(sanitize_html=True)
        parsed = parser.parse_raw_bytes(sample_raw_email_with_dangerous_html)

        assert "javascript:" not in parsed.body_html.lower()

    def test_html_sanitization_preserves_safe_html(self, sample_raw_email_html_only):
        parser = EmailParser(sanitize_html=True)
        parsed = parser.parse_raw_bytes(sample_raw_email_html_only)

        assert "<html>" in parsed.body_html
        assert "<b>" in parsed.body_html
        assert "world" in parsed.body_html

    def test_no_sanitization_when_disabled(self, sample_raw_email_with_dangerous_html):
        parser = EmailParser(sanitize_html=False)
        parsed = parser.parse_raw_bytes(sample_raw_email_with_dangerous_html)

        assert "<script>" in parsed.body_html
        assert "onclick" in parsed.body_html

    def test_decode_header_value_plain(self):
        parser = EmailParser()
        assert parser._decode_header_value("Hello World") == "Hello World"

    def test_decode_header_value_empty(self):
        parser = EmailParser()
        assert parser._decode_header_value("") == ""
        assert parser._decode_header_value(None) == ""

    def test_parse_address_list_single(self):
        parser = EmailParser()
        result = parser._parse_address_list("user@example.com")
        assert result == ["user@example.com"]

    def test_parse_address_list_multiple(self):
        parser = EmailParser()
        result = parser._parse_address_list("a@example.com, b@example.com")
        assert "a@example.com" in result
        assert "b@example.com" in result

    def test_parse_address_list_empty(self):
        parser = EmailParser()
        assert parser._parse_address_list("") == []

    def test_parse_date_valid(self):
        parser = EmailParser()
        result = parser._parse_date("Mon, 15 Jan 2024 10:30:00 +0000")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_date_invalid_returns_now(self):
        parser = EmailParser()
        result = parser._parse_date("not-a-date")
        assert result is not None

    def test_parse_date_none_returns_now(self):
        parser = EmailParser()
        result = parser._parse_date(None)
        assert result is not None

    def test_extract_headers(self, sample_raw_email):
        msg = email.message_from_bytes(sample_raw_email)
        parser = EmailParser()
        headers = parser._extract_headers(msg)

        assert "from" in headers
        assert "to" in headers
        assert "subject" in headers
        assert headers["subject"] == "Test Email"

    def test_decode_payload(self):
        msg = Message()
        msg.set_payload("Hello World".encode("utf-8"), charset="utf-8")
        parser = EmailParser()
        result = parser._decode_payload(msg)
        assert result == "Hello World"

    def test_decode_payload_none(self):
        msg = Message()
        msg["Content-Type"] = "text/plain"
        parser = EmailParser()
        result = parser._decode_payload(msg)
        assert result == ""

    def test_attachment_extraction(self, sample_raw_email_multipart):
        parser = EmailParser()
        parsed = parser.parse_raw_bytes(sample_raw_email_multipart)

        assert len(parsed.attachments) == 1
        att = parsed.attachments[0]
        assert isinstance(att, AttachmentInfo)
        assert att.filename == "report.pdf"
        assert att.size_bytes > 0
        assert isinstance(att.payload, bytes)

    def test_sender_with_name(self):
        raw = (
            b"From: John Doe <john@example.com>\r\n"
            b"To: recipient@example.com\r\n"
            b"Subject: Test\r\n"
            b"Message-ID: <name@example.com>\r\n"
            b"Date: Mon, 15 Jan 2024 10:30:00 +0000\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"Body"
        )
        parser = EmailParser()
        parsed = parser.parse_raw_bytes(raw)
        assert parsed.sender == "John Doe"
        assert parsed.sender_email == "john@example.com"

    def test_multiple_recipients(self):
        raw = (
            b"From: sender@example.com\r\n"
            b"To: a@example.com, b@example.com, c@example.com\r\n"
            b"Subject: Test\r\n"
            b"Message-ID: <multi@example.com>\r\n"
            b"Date: Mon, 15 Jan 2024 10:30:00 +0000\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"Body"
        )
        parser = EmailParser()
        parsed = parser.parse_raw_bytes(raw)
        assert len(parsed.recipients) == 3
        assert "a@example.com" in parsed.recipients
        assert "b@example.com" in parsed.recipients
        assert "c@example.com" in parsed.recipients

    def test_is_read_defaults_to_true(self, sample_raw_email):
        parser = EmailParser()
        parsed = parser.parse_raw_bytes(sample_raw_email)
        assert parsed.is_read is True

    def test_headers_extraction_includes_all(self, sample_raw_email):
        parser = EmailParser()
        parsed = parser.parse_raw_bytes(sample_raw_email)
        assert len(parsed.headers) > 0
        assert "from" in parsed.headers
        assert "to" in parsed.headers

    def test_attachment_without_filename_ignored(self):
        msg = Message()
        msg["Content-Disposition"] = "attachment"
        msg.set_payload(b"data")
        parser = EmailParser()
        result = parser._extract_attachment(msg)
        assert result is None

    def test_decode_header_value_with_encoding(self):
        parser = EmailParser()
        encoded = "=?utf-8?B?SGVsbG8gV29ybGQ=?="
        result = parser._decode_header_value(encoded)
        assert result == "Hello World"
