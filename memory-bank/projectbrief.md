# MCP Email Service - Project Brief

## Project Overview
Build an MCP-compliant email service that connects to IMAP servers and exposes email operations as Model Context Protocol tools.

## Target Stack
- Python
- IMAP protocol
- Model Context Protocol (MCP)

## Core Requirements
- MCP tools: read inbox, search messages, fetch attachments, configure IMAP credentials
- IMAP connection validation on startup
- Connection status reporting
- TLS enforcement
- Secure credential handling (host, port, username, password/app password)

## Error Handling Strategy
- Option B: Consolidate error types + MCP mapping (consolidate IMAP errors and map to MCP error responses)
