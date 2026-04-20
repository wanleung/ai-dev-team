"""Tests for rag-mcp/main.py — tool schemas and health endpoint."""
import sys
import json
import asyncio
import importlib
import importlib.util
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, ANY

# Ensure rag-mcp is on the path
RAG_MCP_DIR = Path(__file__).parent.parent / "rag-mcp"
if str(RAG_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_MCP_DIR))

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
os.environ.setdefault("EMBED_BACKEND", "ollama")


@pytest.fixture()
def main_mod():
    """Load rag-mcp/main.py in isolation, returning the module."""
    # Patch before importing to prevent real db/embedder init
    with patch("db._get_conn", side_effect=Exception("no db")), \
         patch("embedder.Embedder.__init__", return_value=None):
        spec = importlib.util.spec_from_file_location("main_test", RAG_MCP_DIR / "main.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["main_test"] = mod
        spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("main_test", None)


def test_health_endpoint_returns_ok(main_mod):
    """GET /health returns {"status": "ok"}."""
    from starlette.testclient import TestClient
    client = TestClient(main_mod.mcp.streamable_http_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_codebase_tool_registered(main_mod):
    """search_codebase, search_memory, search_docs tools are registered in FastMCP."""
    tool_names = [t.name for t in main_mod.mcp._tool_manager.list_tools()]
    assert "search_codebase" in tool_names
    assert "search_memory" in tool_names
    assert "search_docs" in tool_names


def test_mcp_http_app_is_starlette_app(main_mod):
    """mcp.streamable_http_app() returns a Starlette ASGI app."""
    app = main_mod.mcp.streamable_http_app()
    assert app is not None
    assert hasattr(app, "routes") or callable(app)


def test_search_codebase_returns_results(main_mod):
    """search_codebase() returns uniform {"results": [...]} envelope on success."""
    from models import SearchResult
    
    fake_result = SearchResult(content="x = 1", source_id="src/foo.py", chunk_index=0, score=0.9)
    with patch.object(main_mod._embedder, "embed", return_value=[0.1] * 768), \
         patch("main_test.search_chunks", return_value=[fake_result]):
        result = asyncio.run(main_mod.search_codebase("test query"))
    
    data = json.loads(result)
    assert "results" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) == 1
    assert data["results"][0]["content"] == "x = 1"
    assert data["results"][0]["score"] == 0.9


def test_search_codebase_embedder_error_returns_error_envelope(main_mod):
    """search_codebase() returns {"error": ..., "results": []} on EmbedderError."""
    from embedder import EmbedderError
    
    with patch.object(main_mod._embedder, "embed", side_effect=EmbedderError("backend down")):
        result = asyncio.run(main_mod.search_codebase("q"))
    
    data = json.loads(result)
    assert "error" in data
    assert "backend down" in data["error"]
    assert data["results"] == []


def test_search_codebase_db_exception_returns_error_envelope(main_mod):
    """Generic Exception from search_chunks returns {"error": "TypeName: msg", "results": []}."""
    with patch.object(main_mod._embedder, "embed", return_value=[0.0] * 768), \
         patch("main_test.search_chunks", side_effect=RuntimeError("connection lost")):
        result = asyncio.run(main_mod.search_codebase("q"))
    
    data = json.loads(result)
    assert "error" in data
    assert "RuntimeError" in data["error"]
    assert "connection lost" in data["error"]
    assert data["results"] == []


def test_search_codebase_empty_results(main_mod):
    """search_codebase() returns {"results": []} when no results found."""
    with patch.object(main_mod._embedder, "embed", return_value=[0.0] * 768), \
         patch("main_test.search_chunks", return_value=[]):
        result = asyncio.run(main_mod.search_codebase("nothing"))
    
    data = json.loads(result)
    assert data == {"results": []}


@pytest.mark.parametrize("tool_name", ["search_memory", "search_docs"])
def test_other_search_tools_return_results(main_mod, tool_name):
    """search_memory and search_docs return uniform {"results": [...]} envelope."""
    from models import SearchResult
    
    fake_result = SearchResult(content="hello", source_id="memory/note.md", chunk_index=0, score=0.85)
    with patch.object(main_mod._embedder, "embed", return_value=[0.1] * 768), \
         patch("main_test.search_chunks", return_value=[fake_result]):
        result = asyncio.run(getattr(main_mod, tool_name)("query"))
    
    data = json.loads(result)
    assert "results" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) == 1
    assert data["results"][0]["score"] == 0.85


@pytest.mark.parametrize("tool_name", ["search_memory", "search_docs"])
def test_other_search_tools_embedder_error(main_mod, tool_name):
    """search_memory and search_docs return error envelope on EmbedderError."""
    from embedder import EmbedderError
    with patch.object(main_mod._embedder, "embed", side_effect=EmbedderError("down")):
        result = asyncio.run(getattr(main_mod, tool_name)("q"))
    data = json.loads(result)
    assert "error" in data
    assert "down" in data["error"]
    assert data["results"] == []


@pytest.mark.parametrize("requested,expected", [
    (0, 1),     # floor clamped to 1
    (1, 1),     # at floor
    (5, 5),     # normal
    (100, 100), # at ceiling
    (999, 100), # ceiling clamped
])
def test_search_codebase_top_k_clamping(main_mod, requested, expected):
    """top_k is clamped to [1, _MAX_TOP_K] before the DB call."""
    with patch.object(main_mod._embedder, "embed", return_value=[0.0] * 768), \
         patch("main_test.search_chunks", return_value=[]) as mock_search:
        asyncio.run(main_mod.search_codebase("q", top_k=requested))
    
    mock_search.assert_called_once_with("codebase", ANY, expected)
