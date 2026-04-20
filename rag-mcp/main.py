"""RAG MCP Server — FastMCP server exposing search tools over Streamable HTTP.

Tools:
    search_codebase(query, top_k) — search indexed source code
    search_memory(query, top_k)   — search past pipeline runs
    search_docs(query, top_k)     — search indexed documentation

Transport: Streamable HTTP at /mcp (default FastMCP path)
Health:    GET /health → {"status": "ok"}

Environment variables:
    DATABASE_URL    — Postgres connection string (required)
    EMBED_BACKEND   — ollama | vllm | openai (default: ollama)
    RAG_TOP_K       — default number of results (default: 5)
    (see embedder.py for backend-specific vars)
"""
from __future__ import annotations

import asyncio
import json
import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from db import search_chunks
from embedder import Embedder, EmbedderError

_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))
_embedder = Embedder()

mcp = FastMCP("rag-mcp-server")


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Liveness probe — used by docker-compose healthcheck."""
    return JSONResponse({"status": "ok"})


@mcp.tool()
async def search_codebase(query: str, top_k: int = _TOP_K) -> str:
    """Search the indexed codebase for relevant code chunks.

    Args:
        query: Natural-language description of what you're looking for.
        top_k: Maximum number of results to return (default 5).

    Returns:
        JSON array of SearchResult objects with content, source_id, score, and metadata.
    """
    try:
        embedding = await asyncio.to_thread(_embedder.embed, query)
        results = await asyncio.to_thread(search_chunks, "codebase", embedding, top_k)
        return json.dumps([r.model_dump() for r in results])
    except EmbedderError as exc:
        return json.dumps({"error": f"embedder unavailable: {exc}", "results": []})
    except Exception as exc:
        return json.dumps({"error": str(exc), "results": []})


@mcp.tool()
async def search_memory(query: str, top_k: int = _TOP_K) -> str:
    """Search past pipeline runs for relevant PRD, design, or summary excerpts.

    Args:
        query: Natural-language description of what you're looking for.
        top_k: Maximum number of results to return (default 5).

    Returns:
        JSON array of SearchResult objects with content, source_id (run_id), score, and metadata.
    """
    try:
        embedding = await asyncio.to_thread(_embedder.embed, query)
        results = await asyncio.to_thread(search_chunks, "memory", embedding, top_k)
        return json.dumps([r.model_dump() for r in results])
    except EmbedderError as exc:
        return json.dumps({"error": f"embedder unavailable: {exc}", "results": []})
    except Exception as exc:
        return json.dumps({"error": str(exc), "results": []})


@mcp.tool()
async def search_docs(query: str, top_k: int = _TOP_K) -> str:
    """Search indexed documentation for relevant content.

    Args:
        query: Natural-language description of what you're looking for.
        top_k: Maximum number of results to return (default 5).

    Returns:
        JSON array of SearchResult objects with content, source_id (file path), score, and metadata.
    """
    try:
        embedding = await asyncio.to_thread(_embedder.embed, query)
        results = await asyncio.to_thread(search_chunks, "docs", embedding, top_k)
        return json.dumps([r.model_dump() for r in results])
    except EmbedderError as exc:
        return json.dumps({"error": f"embedder unavailable: {exc}", "results": []})
    except Exception as exc:
        return json.dumps({"error": str(exc), "results": []})


# ASGI app for uvicorn — used by Dockerfile CMD
mcp_http_app = mcp.streamable_http_app()

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
