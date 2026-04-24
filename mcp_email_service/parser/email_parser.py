"""Email Parser & Normalizer for MCP Email Service.

Converts raw RFC822 MIME messages into structured, queryable objects
with plain/HTML body extraction, attachment handling, and HTML sanitization.
"""

import email
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class AttachmentInfo:
    """Represents a parsed email attachment."""

    filename: str
    content_type: str
    size_bytes: int
    payload: bytes
    content_id: Optional[str] = None


@dataclass
class ParsedEmail:
    """Normalized email message extracted from raw RFC822 data."""

    message_id: str
    subject: str
    sender: str
    sender_email: str
    recipients: list[str]
    recipients_raw: str
    date_received: datetime
    body_text: str
    body_html: str
    has_attachments: bool
    attachments: list[AttachmentInfo] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    is_read: bool = True


class EmailParser:
    """Parses raw RFC822 MIME messages into structured ParsedEmail objects.

    Handles MIME multipart decoding, character set detection, HTML sanitization,
    and attachment extraction.
    """

    def __init__(self, sanitize_html: bool = True) -> None:
        """Initialize the email parser.

        Args:
            sanitize_html: Whether to sanitize HTML body content by removing
                          scripts, event handlers, and potentially dangerous tags.
        """
        self._sanitize_html = sanitize_html

    def parse_raw_bytes(self, raw_bytes: bytes) -> ParsedEmail:
        """Parse raw RFC822 email bytes into a normalized ParsedEmail object.

        Args:
            raw_bytes: Raw email message bytes as retrieved from IMAP server.

        Returns:
            ParsedEmail with all headers, body, and attachments extracted.

        Raises:
            ValueError: If the raw bytes cannot be parsed as a valid email message.
        """
        try:
            msg = email.message_from_bytes(raw_bytes)
        except Exception as exc:
            raise ValueError(f"Failed to parse raw email bytes: {exc}") from exc

        return self._parse_message(msg)

    def parse_message(self, msg: Message) -> ParsedEmail:
        """Parse an email.message.Message object into a ParsedEmail.

        Args:
            msg: Pre-parsed email Message object.

        Returns:
            ParsedEmail with all headers, body, and attachments extracted.
        """
        return self._parse_message(msg)

    def _parse_message(self, msg: Message) -> ParsedEmail:
        """Internal method to parse a Message object into ParsedEmail."""
        headers = self._extract_headers(msg)
        message_id = self._decode_header_value(msg.get("Message-ID", ""))
        subject = self._decode_header_value(msg.get("Subject", ""))

        sender_raw = msg.get("From", "")
        sender_name, sender_email = parseaddr(sender_raw)
        sender_name = sender_name or sender_email

        recipients_raw = msg.get("To", "")
        recipients = self._parse_address_list(recipients_raw)

        date_received = self._parse_date(msg.get("Date"))

        body_text, body_html, attachments = self._extract_body_and_attachments(msg)

        if self._sanitize_html and body_html:
            body_html = self._sanitize_html_content(body_html)

        has_attachments = len(attachments) > 0

        return ParsedEmail(
            message_id=message_id,
            subject=subject,
            sender=sender_name,
            sender_email=sender_email,
            recipients=recipients,
            recipients_raw=recipients_raw,
            date_received=date_received,
            body_text=body_text,
            body_html=body_html,
            has_attachments=has_attachments,
            attachments=attachments,
            headers=headers,
        )

    def _extract_headers(self, msg: Message) -> dict[str, str]:
        """Extract all headers as a dictionary with decoded values."""
        headers = {}
        for key, value in msg.items():
            decoded = self._decode_header_value(value)
            headers[key.lower()] = decoded
        return headers

    def _decode_header_value(self, header_value: str) -> str:
        """Decode a MIME-encoded header value to a clean string.

        Handles RFC 2047 encoded-words and multi-part headers.
        """
        if not header_value:
            return ""

        try:
            decoded_parts = decode_header(header_value)
            result = []
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    result.append(part.decode(charset or "utf-8", errors="replace"))
                else:
                    result.append(part)
            return " ".join(result).strip()
        except Exception:
            return header_value.strip()

    def _parse_address_list(self, address_string: str) -> list[str]:
        """Parse a comma-separated address string into a list of email addresses."""
        if not address_string:
            return []

        addresses = []
        for addr in address_string.split(","):
            _, email_addr = parseaddr(addr.strip())
            if email_addr:
                addresses.append(email_addr)
        return addresses

    def _parse_date(self, date_str: Optional[str]) -> datetime:
        """Parse an email date header into a timezone-aware datetime."""
        if not date_str:
            return datetime.now()

        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            logger.warning("Failed to parse email date: %s", date_str)
            return datetime.now()

    def _extract_body_and_attachments(
        self, msg: Message
    ) -> tuple[str, str, list[AttachmentInfo]]:
        """Walk the MIME tree to extract text bodies and attachments.

        Returns:
            Tuple of (plain_text_body, html_body, attachments_list).
        """
        body_text = ""
        body_html = ""
        attachments: list[AttachmentInfo] = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in content_disposition or part.get_filename():
                    attachment = self._extract_attachment(part)
                    if attachment:
                        attachments.append(attachment)
                elif content_type == "text/plain" and not body_text:
                    body_text = self._decode_payload(part)
                elif content_type == "text/html" and not body_html:
                    body_html = self._decode_payload(part)
        else:
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                body_text = self._decode_payload(msg)
            elif content_type == "text/html":
                body_html = self._decode_payload(msg)

        return body_text.strip(), body_html.strip(), attachments

    def _decode_payload(self, part: Message) -> str:
        """Decode a message part's payload to a string.

        Handles charset detection and fallback to UTF-8.
        """
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""

        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return payload.decode("utf-8", errors="replace")

    def _extract_attachment(self, part: Message) -> Optional[AttachmentInfo]:
        """Extract attachment metadata and payload from a MIME part."""
        filename = part.get_filename()
        if not filename:
            return None

        filename = self._decode_header_value(filename)
        payload = part.get_payload(decode=True)
        if payload is None:
            return None

        content_id = part.get("Content-ID")
        if content_id:
            content_id = content_id.strip("<>")

        return AttachmentInfo(
            filename=filename,
            content_type=part.get_content_type(),
            size_bytes=len(payload),
            payload=payload,
            content_id=content_id,
        )

    def _sanitize_html_content(self, html: str) -> str:
        """Sanitize HTML by removing scripts, event handlers, and dangerous tags.

        Uses BeautifulSoup to parse and clean HTML content while preserving
        safe formatting and structure.
        """
        soup = BeautifulSoup(html, "html.parser")

        dangerous_tags = [
            "script",
            "style",
            "iframe",
            "object",
            "embed",
            "form",
            "input",
            "button",
            "select",
            "textarea",
        ]

        for tag_name in dangerous_tags:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        for tag in soup.find_all(True):
            attrs_to_remove = []
            for attr in tag.attrs:
                if attr.lower().startswith("on"):
                    attrs_to_remove.append(attr)
            for attr in attrs_to_remove:
                del tag[attr]

            if tag.get("src", "").strip().lower().startswith("javascript:"):
                tag.decompose()
            elif tag.get("href", "").strip().lower().startswith("javascript:"):
                tag.decompose()

        return str(soup)
