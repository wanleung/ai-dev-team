"""Tests for memory_mcp_server.py — tool schemas and each tool's behavior.

Mirrors tests/test_rag_main.py's pattern: load the module fresh per test
(pointed at a temp SQLite file so tests never touch a real memory.db), call
the @mcp.tool()-decorated async functions directly, and check the JSON
response envelope.
"""
import asyncio
import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parent.parent / "memory_mcp_server.py"


@pytest.fixture()
def server_mod(tmp_path, monkeypatch):
    """Load memory_mcp_server.py fresh, backed by a temp SQLite file."""
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MEMORY_DB_PATH", str(db_path))

    spec = importlib.util.spec_from_file_location("memory_mcp_server_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["memory_mcp_server_test"] = mod
    spec.loader.exec_module(mod)
    yield mod
    mod._store.close()
    sys.modules.pop("memory_mcp_server_test", None)


# ── Tool registration ────────────────────────────────────────────────────────

def test_all_tools_registered(server_mod):
    tool_names = {t.name for t in server_mod.mcp._tool_manager.list_tools()}
    assert tool_names == {
        "memory_write_fact",
        "memory_resolve_fact",
        "memory_forget_fact",
        "memory_write_static",
        "memory_forget_static",
        "memory_recall",
    }


# ── memory_write_fact ────────────────────────────────────────────────────────

def test_write_fact_returns_id(server_mod):
    result = asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="403 errors from dedup", fact_type="issue",
        entity="RSS watcher", resolved=False,
    ))
    data = json.loads(result)
    assert "id" in data
    assert isinstance(data["id"], int)


def test_write_fact_persists_to_the_store(server_mod):
    asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="403 errors", fact_type="issue", resolved=False,
    ))
    facts = server_mod._store.list_facts("owner/repo")
    assert len(facts) == 1
    assert facts[0]["fact"] == "403 errors"


def test_write_fact_rejects_invalid_fact_type(server_mod):
    result = asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="something", fact_type="bogus",
    ))
    data = json.loads(result)
    assert "error" in data
    assert server_mod._store.list_facts("owner/repo") == []


def test_write_fact_rejects_empty_fact_text(server_mod):
    result = asyncio.run(server_mod.memory_write_fact(repo="owner/repo", fact="   "))
    data = json.loads(result)
    assert "error" in data


def test_write_fact_with_supersedes_marks_old_fact_not_latest(server_mod):
    old = json.loads(asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="DB is Postgres 16",
    )))
    asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="DB is Postgres 17", supersedes=old["id"],
    ))
    current = server_mod._store.list_facts("owner/repo")
    assert len(current) == 1
    assert current[0]["fact"] == "DB is Postgres 17"


def test_write_fact_supersedes_zero_means_no_supersession(server_mod):
    result = json.loads(asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="a fact", supersedes=0,
    )))
    row = server_mod._store.list_facts("owner/repo", include_superseded=True)[0]
    assert row["supersedes_id"] is None


# ── memory_resolve_fact ──────────────────────────────────────────────────────

def test_resolve_fact_marks_resolved(server_mod):
    fact_id = json.loads(asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="an issue", fact_type="issue", resolved=False,
    )))["id"]

    result = asyncio.run(server_mod.memory_resolve_fact(repo="owner/repo", fact_id=fact_id))
    assert json.loads(result) == {"resolved": True}
    assert server_mod._store.list_facts("owner/repo", fact_type="issue", resolved=False) == []


def test_resolve_fact_returns_false_for_unknown_id(server_mod):
    result = asyncio.run(server_mod.memory_resolve_fact(repo="owner/repo", fact_id=99999))
    assert json.loads(result) == {"resolved": False}


def test_resolve_fact_scoped_to_repo(server_mod):
    """A fact_id from one repo cannot be resolved via a different repo's call."""
    fact_id = json.loads(asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo-a", fact="an issue", fact_type="issue", resolved=False,
    )))["id"]

    result = asyncio.run(server_mod.memory_resolve_fact(repo="owner/repo-b", fact_id=fact_id))
    assert json.loads(result) == {"resolved": False}
    assert server_mod._store.list_facts("owner/repo-a", fact_type="issue", resolved=False) != []


# ── memory_forget_fact ───────────────────────────────────────────────────────

def test_forget_fact_deletes(server_mod):
    fact_id = json.loads(asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="noise",
    )))["id"]

    result = asyncio.run(server_mod.memory_forget_fact(repo="owner/repo", fact_id=fact_id))
    assert json.loads(result) == {"deleted": True}
    assert server_mod._store.list_facts("owner/repo") == []


def test_forget_fact_returns_false_for_unknown_id(server_mod):
    result = asyncio.run(server_mod.memory_forget_fact(repo="owner/repo", fact_id=99999))
    assert json.loads(result) == {"deleted": False}


def test_forget_fact_scoped_to_repo(server_mod):
    fact_id = json.loads(asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo-a", fact="a fact",
    )))["id"]

    result = asyncio.run(server_mod.memory_forget_fact(repo="owner/repo-b", fact_id=fact_id))
    assert json.loads(result) == {"deleted": False}
    assert len(server_mod._store.list_facts("owner/repo-a")) == 1


# ── memory_write_static ──────────────────────────────────────────────────────

def test_write_static_returns_id(server_mod):
    result = asyncio.run(server_mod.memory_write_static(
        repo="owner/repo", fact="Target DB is Postgres 16 + PostGIS", key="tech-stack",
    ))
    data = json.loads(result)
    assert "id" in data


def test_write_static_same_key_updates_in_place(server_mod):
    first = json.loads(asyncio.run(server_mod.memory_write_static(
        repo="owner/repo", fact="Postgres 16", key="tech-stack",
    )))
    second = json.loads(asyncio.run(server_mod.memory_write_static(
        repo="owner/repo", fact="Postgres 17", key="tech-stack",
    )))
    assert first["id"] == second["id"]
    facts = server_mod._store.list_static("owner/repo")
    assert len(facts) == 1
    assert facts[0]["fact"] == "Postgres 17"


def test_write_static_rejects_empty_fact_text(server_mod):
    result = asyncio.run(server_mod.memory_write_static(repo="owner/repo", fact=""))
    assert "error" in json.loads(result)


# ── memory_forget_static ─────────────────────────────────────────────────────

def test_forget_static_deletes_by_key(server_mod):
    asyncio.run(server_mod.memory_write_static(repo="owner/repo", fact="fact", key="k"))
    result = asyncio.run(server_mod.memory_forget_static(repo="owner/repo", key="k"))
    assert json.loads(result) == {"deleted": True}
    assert server_mod._store.list_static("owner/repo") == []


def test_forget_static_returns_false_for_unknown_key(server_mod):
    result = asyncio.run(server_mod.memory_forget_static(repo="owner/repo", key="nonexistent"))
    assert json.loads(result) == {"deleted": False}


# ── memory_recall ────────────────────────────────────────────────────────────

def test_recall_returns_empty_context_when_nothing_recorded(server_mod):
    result = asyncio.run(server_mod.memory_recall(repo="owner/repo"))
    assert json.loads(result) == {"context": ""}


def test_recall_reflects_writes_made_through_the_tools(server_mod):
    asyncio.run(server_mod.memory_write_static(
        repo="owner/repo", fact="Always use HK Cantonese terminology", key="tone",
    ))
    result = asyncio.run(server_mod.memory_recall(repo="owner/repo"))
    data = json.loads(result)
    assert "Always use HK Cantonese terminology" in data["context"]


def test_recall_reflects_resolve_removing_an_open_issue(server_mod):
    fact_id = json.loads(asyncio.run(server_mod.memory_write_fact(
        repo="owner/repo", fact="an open issue", fact_type="issue", resolved=False,
    )))["id"]
    before = json.loads(asyncio.run(server_mod.memory_recall(repo="owner/repo")))
    assert "an open issue" in before["context"]

    asyncio.run(server_mod.memory_resolve_fact(repo="owner/repo", fact_id=fact_id))
    after = json.loads(asyncio.run(server_mod.memory_recall(repo="owner/repo")))
    assert "an open issue" not in after["context"]
