"""Embedding client with Ollama, vLLM, and OpenAI backends.

Backend is selected by the EMBED_BACKEND environment variable:
  - 'ollama'  (default): POST /api/embeddings to OLLAMA_BASE_URL
  - 'vllm':              POST /v1/embeddings to VLLM_BASE_URL
  - 'openai':            OpenAI SDK with OPENAI_API_KEY
"""
from __future__ import annotations

import os

import requests
import requests.exceptions

from models import EmbedderError

_BACKEND = os.environ.get("EMBED_BACKEND", "ollama")
_OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "nomic-embed-text")
_VLLM_BASE = os.environ.get("VLLM_BASE_URL", "http://localhost:8000").rstrip("/")
_VLLM_MODEL = os.environ.get("VLLM_MODEL", "BAAI/bge-m3")
_OPENAI_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
_TIMEOUT = 30


class Embedder:
    """Generates text embeddings using the configured backend."""

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for a single text string.

        Raises:
            EmbedderError: If the backend is unreachable or returns an error.
        """
        try:
            if _BACKEND == "ollama":
                return self._embed_ollama(text)
            elif _BACKEND == "vllm":
                return self._embed_vllm(text)
            elif _BACKEND == "openai":
                return self._embed_openai(text)
            else:
                raise EmbedderError(f"Unknown EMBED_BACKEND: {_BACKEND!r}")
        except EmbedderError:
            raise
        except Exception as exc:
            raise EmbedderError(f"Embedding failed ({_BACKEND}): {exc}") from exc

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for a list of texts.

        Calls embed() per item. Raises EmbedderError on first failure.
        """
        return [self.embed(t) for t in texts]

    # ── backends ──────────────────────────────────────────────────────────────

    def _embed_ollama(self, text: str) -> list[float]:
        url = f"{_OLLAMA_BASE}/api/embeddings"
        try:
            resp = requests.post(
                url,
                json={"model": _OLLAMA_MODEL, "prompt": text},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise EmbedderError(str(exc)) from exc
        return resp.json()["embedding"]

    def _embed_vllm(self, text: str) -> list[float]:
        url = f"{_VLLM_BASE}/v1/embeddings"
        try:
            resp = requests.post(
                url,
                json={"model": _VLLM_MODEL, "input": text},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise EmbedderError(str(exc)) from exc
        return resp.json()["data"][0]["embedding"]

    def _embed_openai(self, text: str) -> list[float]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EmbedderError("openai package not installed") from exc
        client = OpenAI()
        resp = client.embeddings.create(model=_OPENAI_MODEL, input=text)
        return resp.data[0].embedding
