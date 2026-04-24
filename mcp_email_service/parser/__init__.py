"""Email Parser & Normalizer for MCP Email Service.

Parses raw RFC822 MIME messages into structured, queryable objects
with plain/HTML body extraction, attachment handling, and HTML sanitization.
"""

from parser.email_parser import EmailParser, ParsedEmail

__all__ = ["EmailParser", "ParsedEmail"]
