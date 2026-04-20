"""Pydantic models for the RAG MCP server."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    content: str
    source_id: str
    chunk_index: int
    score: float = Field(ge=0.0, le=1.0, description="Cosine similarity (1 - pgvector distance)")
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbedderError(Exception):
    """Raised when the embedding backend is unreachable or returns an error."""
