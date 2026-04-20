"""Tests for rag-mcp/embedder.py — all backends mocked."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag-mcp"))

import json
from unittest.mock import MagicMock, patch
import pytest


# ── Ollama ────────────────────────────────────────────────────────────────────

def test_ollama_embed_sends_correct_request(monkeypatch):
    """Ollama backend POSTs to /api/embeddings with model+prompt."""
    monkeypatch.setenv("EMBED_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.10:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "nomic-embed-text")

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
    fake_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=fake_resp) as mock_post:
        import importlib
        import embedder as emb_mod
        importlib.reload(emb_mod)
        e = emb_mod.Embedder()
        result = e.embed("hello")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["url"]
    assert "/api/embeddings" in url
    body = call_kwargs[1].get("json") or call_kwargs[0][1]
    assert body["model"] == "nomic-embed-text"
    assert body["prompt"] == "hello"
    assert result == [0.1, 0.2, 0.3]


def test_ollama_embed_raises_embedder_error_on_network_failure(monkeypatch):
    """Ollama backend wraps requests.exceptions.ConnectionError as EmbedderError."""
    monkeypatch.setenv("EMBED_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.10:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "nomic-embed-text")

    import requests as req_mod
    with patch("requests.post", side_effect=req_mod.exceptions.ConnectionError("refused")):
        import importlib
        import embedder as emb_mod
        importlib.reload(emb_mod)
        e = emb_mod.Embedder()
        with pytest.raises(emb_mod.EmbedderError, match="refused"):
            e.embed("hello")


# ── vLLM ─────────────────────────────────────────────────────────────────────

def test_vllm_embed_sends_correct_request(monkeypatch):
    """vLLM backend POSTs to /v1/embeddings with model+input."""
    monkeypatch.setenv("EMBED_BACKEND", "vllm")
    monkeypatch.setenv("VLLM_BASE_URL", "http://192.168.1.10:8000")
    monkeypatch.setenv("VLLM_MODEL", "BAAI/bge-m3")

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"data": [{"embedding": [0.5, 0.6]}]}
    fake_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=fake_resp) as mock_post:
        import importlib
        import embedder as emb_mod
        importlib.reload(emb_mod)
        e = emb_mod.Embedder()
        result = e.embed("world")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["url"]
    assert "/v1/embeddings" in url
    body = call_kwargs[1].get("json") or call_kwargs[0][1]
    assert body["model"] == "BAAI/bge-m3"
    assert body["input"] == "world"
    assert result == [0.5, 0.6]


# ── embed_batch ───────────────────────────────────────────────────────────────

def test_embed_batch_returns_list_of_embeddings(monkeypatch):
    """embed_batch() calls embed() for each text and returns a list."""
    monkeypatch.setenv("EMBED_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "nomic-embed-text")

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()

    call_count = 0

    def fake_post(url, json=None, timeout=None):
        nonlocal call_count
        call_count += 1
        fake_resp.json.return_value = {"embedding": [float(call_count)] * 3}
        return fake_resp

    with patch("requests.post", side_effect=fake_post):
        import importlib
        import embedder as emb_mod
        importlib.reload(emb_mod)
        e = emb_mod.Embedder()
        results = e.embed_batch(["a", "b", "c"])

    assert len(results) == 3
    assert results[0] == [1.0, 1.0, 1.0]
    assert results[1] == [2.0, 2.0, 2.0]
    assert results[2] == [3.0, 3.0, 3.0]


def test_embed_raises_for_empty_text(monkeypatch):
    """embed() raises EmbedderError for empty or whitespace-only text."""
    monkeypatch.setenv("EMBED_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "nomic-embed-text")

    import importlib
    import embedder as emb_mod
    importlib.reload(emb_mod)
    e = emb_mod.Embedder()
    with pytest.raises(emb_mod.EmbedderError, match="non-empty"):
        e.embed("")
    with pytest.raises(emb_mod.EmbedderError, match="non-empty"):
        e.embed("   ")


def test_unknown_backend_raises_embedder_error(monkeypatch):
    """Unknown EMBED_BACKEND raises EmbedderError."""
    monkeypatch.setenv("EMBED_BACKEND", "bogus_backend")

    import importlib
    import embedder as emb_mod
    importlib.reload(emb_mod)
    e = emb_mod.Embedder()
    with pytest.raises(emb_mod.EmbedderError, match="Unknown EMBED_BACKEND"):
        e.embed("hello")


def test_ollama_raises_on_unexpected_response(monkeypatch):
    """Ollama backend raises EmbedderError if response body lacks 'embedding' key."""
    monkeypatch.setenv("EMBED_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "nomic-embed-text")

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"error": "model not found"}

    with patch("requests.post", return_value=fake_resp):
        import importlib
        import embedder as emb_mod
        importlib.reload(emb_mod)
        e = emb_mod.Embedder()
        with pytest.raises(emb_mod.EmbedderError, match="Unexpected Ollama response"):
            e.embed("hello")
