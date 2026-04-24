# Product Context

## Purpose
Provide an MCP-compliant email service that enables AI assistants to interact with email accounts via IMAP protocol.

## Target Users
- AI assistants needing email access through Model Context Protocol
- Developers integrating email capabilities into MCP-enabled applications

## Core Capabilities
- Read inbox messages
- Search email messages
- Fetch email attachments
- Configure IMAP credentials (host, port, username, password/app password)
- Validate IMAP connection on startup
- Report connection status

## Design Decisions
- Error handling: Option B (Consolidate + MCP mapping) - consolidate error types and map IMAP errors to MCP error responses for operational clarity and MCP protocol compatibility
