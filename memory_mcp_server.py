"""memory_mcp_server.py — MCP server exposing MemoryStore's write/forget/resolve
operations as agent-callable tools, over stdio.

Pairs with rag-mcp's search_memory (semantic read access to memory.db, via
pgvector) — this server is the write side. rag-mcp runs in its own Docker
container with no filesystem access to workspace/memory.db, only network;
this server runs as a plain stdio subprocess on the same host as the
orchestrator, so it can import MemoryStore directly and write to the SQLite
file that's the actual source of truth.

An agent that only ever gets recall()'s injected context at the start of a
run can't act on anything it learns mid-task — it can look something up
(search_memory) but not record what it found. These tools close that loop:
write a new fact, mark an issue resolved, retract something wrong, or pull
a fresh copy of the full memory context after making a change.

Tools:
    memory_write_fact(repo, fact, fact_type, entity, resolved, supersedes)
    memory_resolve_fact(repo, fact_id)
    memory_forget_fact(repo, fact_id)
    memory_write_static(repo, fact, key)
    memory_forget_static(repo, key)
    memory_recall(repo)

Transport: stdio — spawned as a subprocess by MCPToolRegistry
(tools/mcp_registry.py). Add to config.yaml / config.local.yaml:

    mcp:
      servers:
        - name: memory
          type: stdio
          command: python
          args: ["memory_mcp_server.py"]
          env:
            MEMORY_DB_PATH: "./workspace/memory.db"

Environment variables:
    MEMORY_DB_PATH — path to the MemoryStore SQLite file
                     (default: ./workspace/memory.db, matching MemoryStore's own default)
"""
from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from memory_store import MemoryStore

_DB_PATH = os.environ.get("MEMORY_DB_PATH", "./workspace/memory.db")
_store = MemoryStore(_DB_PATH)

mcp = FastMCP("memory-mcp-server")

_VALID_FACT_TYPES = {"decision", "issue", "learning", "status"}


@mcp.tool()
async def memory_write_fact(
    repo: str,
    fact: str,
    fact_type: str = "status",
    entity: str = "",
    resolved: bool = True,
    supersedes: int = 0,
) -> str:
    """Record one atomic fact for a repo: a decision, an issue, a learning, or a status update.

    Use this when you discover or decide something worth remembering beyond
    this run — the same kind of fact FactExtractorAgent pulls from a run
    summary automatically, but recorded the moment you learn it instead of
    waiting for the run to finish.

    Args:
        repo: Repo slug this fact applies to (e.g. "owner/repo").
        fact: One self-contained sentence — specific and factual.
        fact_type: One of "decision", "issue", "learning", "status".
        entity: What/who the fact is about (a component, module, stage).
        resolved: For fact_type="issue", whether it's already fixed.
            Ignored in spirit (but still stored) for other types.
        supersedes: id of an existing fact this one updates or replaces.
            Pass 0 (default) if this isn't updating anything — the old fact
            stays in the table but recall() stops surfacing it once
            superseded.

    Returns:
        JSON {"id": <new fact id>}, or {"error": "..."} on failure.
    """
    try:
        ft = fact_type.strip().lower()
        if ft not in _VALID_FACT_TYPES:
            return json.dumps({"error": f"fact_type must be one of {sorted(_VALID_FACT_TYPES)}"})
        fact_text = fact.strip()
        if not fact_text:
            return json.dumps({"error": "fact text must not be empty"})
        fact_id = _store.save_fact(
            repo=repo,
            fact=fact_text,
            fact_type=ft,
            entity=entity.strip(),
            resolved=resolved,
            supersedes_id=supersedes or None,
        )
        return json.dumps({"id": fact_id})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


@mcp.tool()
async def memory_resolve_fact(repo: str, fact_id: int) -> str:
    """Mark an issue-type fact as resolved — the issue happened and is now fixed.

    Args:
        repo: Repo slug — the fact must belong to this repo or nothing happens.
        fact_id: The fact's id, from memory_write_fact's response or search_memory.

    Returns:
        JSON {"resolved": true/false} — false if no matching fact was found
        for that repo.
    """
    try:
        ok = _store.resolve_fact(fact_id, repo=repo)
        return json.dumps({"resolved": ok})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


@mcp.tool()
async def memory_forget_fact(repo: str, fact_id: int) -> str:
    """Delete a fact outright — use when it was noise, a duplicate, or simply wrong.

    Distinct from memory_resolve_fact: a resolved fact stays in memory as a
    record that something happened and got fixed. A forgotten fact is
    removed entirely, as if it had never been recorded.

    Args:
        repo: Repo slug — the fact must belong to this repo or nothing happens.
        fact_id: The fact's id.

    Returns:
        JSON {"deleted": true/false} — false if no matching fact was found
        for that repo.
    """
    try:
        ok = _store.forget_fact(fact_id, repo=repo)
        return json.dumps({"deleted": ok})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


@mcp.tool()
async def memory_write_static(repo: str, fact: str, key: str = "") -> str:
    """Record or update a standing fact — recall() always includes these in full, regardless of relevance.

    Use for facts that should always be known: architecture choices, naming
    conventions, standing preferences. Not for time-bound status updates —
    use memory_write_fact for those.

    Args:
        repo: Repo slug this fact applies to.
        fact: The fact text.
        key: Optional stable identifier (e.g. "tech-stack"). When given and
            a static fact with the same key already exists for this repo,
            it's updated in place instead of duplicated. Omit to always add
            a new fact.

    Returns:
        JSON {"id": <fact id>} (the existing row's id if this updated one
        by key), or {"error": "..."} on failure.
    """
    try:
        fact_text = fact.strip()
        if not fact_text:
            return json.dumps({"error": "fact text must not be empty"})
        fact_id = _store.save_static(repo=repo, fact=fact_text, key=key or None)
        return json.dumps({"id": fact_id})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


@mcp.tool()
async def memory_forget_static(repo: str, key: str) -> str:
    """Delete a standing fact by its key.

    Args:
        repo: Repo slug the fact belongs to.
        key: The stable identifier passed to memory_write_static when it was created.

    Returns:
        JSON {"deleted": true/false} — false if no fact with that key exists
        for this repo.
    """
    try:
        ok = _store.forget_static(repo, key)
        return json.dumps({"deleted": ok})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


@mcp.tool()
async def memory_recall(repo: str) -> str:
    """Return the current full memory context for a repo.

    Static facts, open issues, and recent tiered history — the same content
    injected into agent prompts at the start of a run. Call this mid-task
    to see the latest state after writing, resolving, or forgetting a fact.

    Args:
        repo: Repo slug to recall memory for.

    Returns:
        JSON {"context": "<markdown text>"} — context is "" if nothing has
        been recorded for this repo yet.
    """
    try:
        context = _store.recall(repo)
        return json.dumps({"context": context})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    mcp.run()  # stdio by default
