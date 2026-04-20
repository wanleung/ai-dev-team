"""Tests for rag-mcp/main.py — tool schemas and health endpoint."""
import sys, os

# Absolute path to rag-mcp directory
rag_mcp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rag-mcp")
if rag_mcp_dir not in sys.path:
    sys.path.insert(0, rag_mcp_dir)

import json
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
