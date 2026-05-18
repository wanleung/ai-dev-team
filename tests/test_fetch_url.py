"""Tests for the fetch_url tool."""
from __future__ import annotations
from unittest.mock import patch, MagicMock
import pytest
from tools.fetch_url import fetch_url, fetch_url_tools


def _mock_response(html: str) -> MagicMock:
    """Build a mock requests.Response for streaming tests."""
    content = html.encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.encoding = "utf-8"
    mock_resp.iter_content.return_value = iter([content])
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_fetch_url_returns_text():
    html = "<html><head><title>Test</title></head><body><p>Hello world</p></body></html>"
    with patch("tools.fetch_url.requests.get", return_value=_mock_response(html)):
        result = fetch_url("https://example.com")
    assert "Hello world" in result


def test_fetch_url_strips_scripts():
    html = "<html><body><script>evil()</script><p>Real content</p></body></html>"
    with patch("tools.fetch_url.requests.get", return_value=_mock_response(html)):
        result = fetch_url("https://example.com")
    assert "evil" not in result
    assert "Real content" in result


def test_fetch_url_truncates_to_max_chars():
    long_content = "x" * 20000
    html = f"<html><body><p>{long_content}</p></body></html>"
    with patch("tools.fetch_url.requests.get", return_value=_mock_response(html)):
        result = fetch_url("https://example.com", max_chars=8000)
    assert len(result) <= 8000


def test_fetch_url_registered_in_registry():
    schema_names = [s["function"]["name"] for s in fetch_url_tools.schemas]
    assert "fetch_url" in schema_names


def test_fetch_url_http_error_returns_error_string():
    import requests as req_lib
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = req_lib.HTTPError("404")
    with patch("tools.fetch_url.requests.get", return_value=mock_resp):
        result = fetch_url("https://example.com/404")
    assert result.startswith("[Error fetching")
