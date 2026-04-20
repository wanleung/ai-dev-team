"""Pydantic models for the RAG MCP server."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SearchResult(BaseModel):
    content: str
    source_id: str
    chunk_index: int
    score: float
    metadata: dict[str, Any] = {}


class EmbedderError(Exception):
    """Raised when the embedding backend is unreachable or returns an error."""
