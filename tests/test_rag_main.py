"""Tests for rag-mcp/main.py — tool schemas and health endpoint."""
import sys, os
import asyncio
import json

# Absolute path to rag-mcp directory
rag_mcp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rag-mcp")
if rag_mcp_dir not in sys.path:
    sys.path.insert(0, rag_mcp_dir)

from unittest.mock import AsyncMock, patch, MagicMock
import pytest



def test_health_endpoint_returns_ok():
    """GET /health returns {"status": "ok"}."""
    from starlette.testclient import TestClient
    os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    os.environ.setdefault("EMBED_BACKEND", "ollama")

    with patch("db._get_conn", side_effect=Exception("no db")), \
         patch("embedder.Embedder.embed", side_effect=Exception("no embed")):
        import importlib.util
        # Load main.py explicitly from rag-mcp directory
        main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rag-mcp", "main.py")
        spec = importlib.util.spec_from_file_location("main", main_path)
        main_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_mod)
        app = main_mod.mcp.streamable_http_app()

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_search_codebase_tool_registered():
    """search_codebase, search_memory, search_docs tools are registered in FastMCP."""
    os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    os.environ.setdefault("EMBED_BACKEND", "ollama")

    with patch("db._get_conn", side_effect=Exception("no db")), \
         patch("embedder.Embedder.embed", side_effect=Exception("no embed")):
        import importlib.util
        # Load main.py explicitly from rag-mcp directory
        main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rag-mcp", "main.py")
        spec = importlib.util.spec_from_file_location("main", main_path)
        main_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_mod)

        tool_names = [t.name for t in main_mod.mcp._tool_manager.list_tools()]
        assert "search_codebase" in tool_names
        assert "search_memory" in tool_names
        assert "search_docs" in tool_names


def test_mcp_http_app_is_starlette_app():
    """mcp_http_app is a Starlette ASGI app."""
    os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    os.environ.setdefault("EMBED_BACKEND", "ollama")

    with patch("db._get_conn", side_effect=Exception("no db")), \
         patch("embedder.Embedder.embed", side_effect=Exception("no embed")):
        import importlib.util
        # Load main.py explicitly from rag-mcp directory
        main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rag-mcp", "main.py")
        spec = importlib.util.spec_from_file_location("main", main_path)
        main_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_mod)

        assert hasattr(main_mod, "mcp_http_app")
        assert main_mod.mcp_http_app is not None


def test_search_codebase_returns_results():
    """search_codebase() returns uniform {"results": [...]} envelope on success."""
    os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    os.environ.setdefault("EMBED_BACKEND", "ollama")

    import importlib.util
    from models import SearchResult

    # Load main module with db/embedder mocked
    with patch("db._get_conn", side_effect=Exception("no db")), \
         patch("db.search_chunks") as mock_search:
        main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rag-mcp", "main.py")
        spec = importlib.util.spec_from_file_location("main", main_path)
        main_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_mod)

        fake_result = SearchResult(content="x = 1", source_id="src/foo.py", chunk_index=0, score=0.9)
        mock_search.return_value = [fake_result]

        with patch.object(main_mod._embedder, "embed", return_value=[0.1] * 768):
            result = asyncio.run(main_mod.search_codebase("test query"))

    data = json.loads(result)
    assert "results" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) == 1
    assert data["results"][0]["content"] == "x = 1"
    assert data["results"][0]["score"] == 0.9


def test_search_codebase_embedder_error_returns_error_envelope():
    """search_codebase() returns {"error": ..., "results": []} on EmbedderError."""
    os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    os.environ.setdefault("EMBED_BACKEND", "ollama")

    import importlib.util
    from embedder import EmbedderError

    with patch("db._get_conn", side_effect=Exception("no db")):
        main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rag-mcp", "main.py")
        spec = importlib.util.spec_from_file_location("main", main_path)
        main_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_mod)

    with patch.object(main_mod._embedder, "embed", side_effect=EmbedderError("backend down")):
        result = asyncio.run(main_mod.search_codebase("q"))

    data = json.loads(result)
    assert "error" in data
    assert "backend down" in data["error"]
    assert data["results"] == []


def test_search_codebase_empty_results():
    """search_codebase() returns {"results": []} when no results found."""
    os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    os.environ.setdefault("EMBED_BACKEND", "ollama")

    import importlib.util

    with patch("db._get_conn", side_effect=Exception("no db")), \
         patch("db.search_chunks") as mock_search:
        main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rag-mcp", "main.py")
        spec = importlib.util.spec_from_file_location("main", main_path)
        main_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_mod)

        mock_search.return_value = []

        with patch.object(main_mod._embedder, "embed", return_value=[0.0] * 768):
            result = asyncio.run(main_mod.search_codebase("nothing"))

    data = json.loads(result)
    assert data == {"results": []}
