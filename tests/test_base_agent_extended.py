"""Extended tests for BaseAgent: memory injection, tool-call dispatch, MCP session.

Tests behaviors added/expected in low-priority coverage:
- Memory injection into call() when memory_store is set
- Tool-call dispatch in call_with_tools()
- MCP session creation when mcp_server_url is configured

Tests use pytest.skip() for features not yet implemented.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.base_agent import BaseAgent


# ──────────────────────────────────────────────────────────────────────────
# Memory injection tests
# ──────────────────────────────────────────────────────────────────────────

def test_call_injects_memory_when_memory_store_set():
    """call() should inject memory entries into prompt when memory_store is set."""
    pytest.skip("BaseAgent.memory_store attribute not yet implemented")
    
    # Expected implementation (once added):
    # agent = BaseAgent(model="gpt-4.1", llm=MagicMock())
    # agent.memory_store = MagicMock()
    # agent.memory_store.search.return_value = ["Memory 1", "Memory 2"]
    # agent._llm.call = MagicMock(return_value="Response")
    # 
    # result = agent.call("Test message")
    # 
    # # Verify memory entries were prepended to the user message
    # called_messages = agent._llm.call.call_args[0][0]
    # assert any("Memory 1" in str(msg) for msg in called_messages)
    # assert any("Memory 2" in str(msg) for msg in called_messages)


def test_call_skips_injection_when_memory_store_none():
    """call() should skip memory injection when memory_store is None."""
    pytest.skip("BaseAgent.memory_store attribute not yet implemented")
    
    # Expected implementation (once added):
    # agent = BaseAgent(model="gpt-4.1", llm=MagicMock())
    # agent.memory_store = None
    # agent._llm.call = MagicMock(return_value="Response")
    # 
    # result = agent.call("Test message")
    # 
    # # Verify no memory search was attempted
    # called_messages = agent._llm.call.call_args[0][0]
    # user_msg = [m for m in called_messages if m.get("role") == "user"][0]
    # assert "Test message" in user_msg["content"]


def test_call_skips_injection_when_memory_search_returns_empty():
    """call() should skip injection when memory_store.search() returns empty."""
    pytest.skip("BaseAgent.memory_store attribute not yet implemented")
    
    # Expected implementation (once added):
    # agent = BaseAgent(model="gpt-4.1", llm=MagicMock())
    # agent.memory_store = MagicMock()
    # agent.memory_store.search.return_value = []
    # agent._llm.call = MagicMock(return_value="Response")
    # 
    # result = agent.call("Test message")
    # 
    # # Verify search was called but nothing was injected
    # agent.memory_store.search.assert_called_once()
    # called_messages = agent._llm.call.call_args[0][0]
    # user_msg = [m for m in called_messages if m.get("role") == "user"][0]
    # assert user_msg["content"] == "Test message"


# ──────────────────────────────────────────────────────────────────────────
# Tool-call dispatch tests
# ──────────────────────────────────────────────────────────────────────────

def test_call_with_tools_dispatches_named_tool():
    """call_with_tools() should dispatch a named tool when LLM returns a tool-call."""
    # Create a mock backend that supports tools
    mock_llm = MagicMock()
    mock_llm.supports_tools.return_value = True
    mock_llm.call_with_tools.return_value = "Tool executed successfully"
    mock_llm.model = "gpt-4.1"
    
    agent = BaseAgent(model="gpt-4.1", llm=mock_llm)
    
    # Create a mock tool registry
    mock_tools = MagicMock()
    
    result = agent.call_with_tools("Execute tool", mock_tools)
    
    # Verify the backend's call_with_tools was invoked
    assert mock_llm.call_with_tools.called
    assert result == "Tool executed successfully"
    
    # Verify the tool registry was passed to the backend
    call_args = mock_llm.call_with_tools.call_args
    assert call_args[0][1] is mock_tools  # Second positional arg should be tools


def test_call_with_tools_raises_on_unsupported_backend():
    """call_with_tools() should raise NotImplementedError on backends without tool support."""
    # Create a mock backend that doesn't support tools
    mock_llm = MagicMock()
    mock_llm.supports_tools.return_value = False
    mock_llm.model = "gpt-4.1"
    
    agent = BaseAgent(model="gpt-4.1", llm=mock_llm)
    mock_tools = MagicMock()
    
    with pytest.raises(NotImplementedError, match="call_with_tools is not supported"):
        agent.call_with_tools("Execute tool", mock_tools)


def test_call_with_tools_passes_max_turns():
    """call_with_tools() should pass max_turns parameter to backend."""
    mock_llm = MagicMock()
    mock_llm.supports_tools.return_value = True
    mock_llm.call_with_tools.return_value = "Response"
    mock_llm.model = "gpt-4.1"
    
    agent = BaseAgent(model="gpt-4.1", llm=mock_llm)
    mock_tools = MagicMock()
    
    agent.call_with_tools("Test", mock_tools, max_turns=12)
    
    # Verify max_turns was passed
    call_args = mock_llm.call_with_tools.call_args
    assert call_args[0][2] == 12  # Third positional arg should be max_turns


def test_call_with_tools_prepends_context():
    """call_with_tools() should prepend context to user_message when provided."""
    mock_llm = MagicMock()
    mock_llm.supports_tools.return_value = True
    mock_llm.call_with_tools.return_value = "Response"
    mock_llm.model = "gpt-4.1"
    
    agent = BaseAgent(model="gpt-4.1", llm=mock_llm)
    agent.system_prompt = ""  # Clear system prompt for easier checking
    mock_tools = MagicMock()
    
    agent.call_with_tools("User message", mock_tools, context="Context info")
    
    # Verify context was prepended
    messages = mock_llm.call_with_tools.call_args[0][0]
    user_msg = [m for m in messages if m.get("role") == "user"][0]
    assert "Context info" in user_msg["content"]
    assert "User message" in user_msg["content"]


def test_call_with_tools_updates_history():
    """call_with_tools() should record the exchange in conversation history."""
    mock_llm = MagicMock()
    mock_llm.supports_tools.return_value = True
    mock_llm.call_with_tools.return_value = "Tool response"
    mock_llm.model = "gpt-4.1"
    
    agent = BaseAgent(model="gpt-4.1", llm=mock_llm)
    mock_tools = MagicMock()
    
    initial_history_len = len(agent._history)
    agent.call_with_tools("Test message", mock_tools)
    
    # History should now include user message and assistant response
    assert len(agent._history) == initial_history_len + 2
    assert agent._history[-2]["role"] == "user"
    assert agent._history[-1]["role"] == "assistant"
    assert agent._history[-1]["content"] == "Tool response"


# ──────────────────────────────────────────────────────────────────────────
# MCP session tests
# ──────────────────────────────────────────────────────────────────────────

def test_mcp_session_created_when_mcp_server_url_configured():
    """MCP session should be created when config includes mcp_server_url."""
    pytest.skip("BaseAgent MCP session creation not yet implemented")
    
    # Expected implementation (once added):
    # with patch("agents.base_agent.MCPSession") as mock_mcp_class:
    #     mock_mcp_instance = MagicMock()
    #     mock_mcp_class.return_value = mock_mcp_instance
    #     
    #     agent = BaseAgent(model="gpt-4.1", mcp_server_url="http://localhost:8080")
    #     
    #     # Verify MCP session was created
    #     mock_mcp_class.assert_called_once_with("http://localhost:8080")
    #     assert agent.mcp_session is mock_mcp_instance


def test_no_mcp_session_when_mcp_server_url_absent():
    """No MCP session should be created when mcp_server_url is not provided."""
    pytest.skip("BaseAgent MCP session creation not yet implemented")
    
    # Expected implementation (once added):
    # agent = BaseAgent(model="gpt-4.1")
    # 
    # # Verify no MCP session exists
    # assert not hasattr(agent, "mcp_session") or agent.mcp_session is None


# ──────────────────────────────────────────────────────────────────────────
# Integration test: call_with_tools with actual tool execution flow
# ──────────────────────────────────────────────────────────────────────────

def test_call_with_tools_full_flow():
    """Integration test: call_with_tools with multi-turn tool execution."""
    mock_llm = MagicMock()
    mock_llm.supports_tools.return_value = True
    mock_llm.model = "gpt-4.1"
    
    # Simulate a multi-turn conversation where LLM calls a tool then responds
    mock_llm.call_with_tools.return_value = "Final answer after tool use"
    
    agent = BaseAgent(model="gpt-4.1", llm=mock_llm)
    mock_tools = MagicMock()
    
    result = agent.call_with_tools(
        "What's the weather?",
        mock_tools,
        context="You are a helpful assistant",
        max_turns=5
    )
    
    # Verify the full call
    assert result == "Final answer after tool use"
    assert mock_llm.call_with_tools.called
    
    # Verify messages structure
    messages = mock_llm.call_with_tools.call_args[0][0]
    assert any(m.get("role") == "user" for m in messages)
    
    # Verify history was updated
    assert len(agent._history) > 0
    assert agent._history[-1]["content"] == "Final answer after tool use"


# ──────────────────────────────────────────────────────────────────────────
# _after_write tests
# ──────────────────────────────────────────────────────────────────────────

def test_after_write_no_violations(tmp_path):
    """_after_write returns empty list when all functions are compliant."""
    f = tmp_path / "ok.py"
    f.write_text("def small():\n    return 1\n")
    llm = MagicMock()
    llm.model = "gpt-4.1"
    llm.supports_tools.return_value = False
    agent = BaseAgent(model="gpt-4.1", llm=llm)
    result = agent._after_write([f])
    assert result == []


def test_after_write_returns_violations(tmp_path):
    """_after_write returns violation strings for oversized functions."""
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    f = tmp_path / "big.py"
    f.write_text(f"def huge():\n{body}\n    return x0\n")
    llm = MagicMock()
    llm.model = "gpt-4.1"
    llm.supports_tools.return_value = False
    agent = BaseAgent(model="gpt-4.1", llm=llm)
    result = agent._after_write([f])
    assert len(result) == 1
    assert "huge" in result[0]


def test_after_write_empty_list():
    """_after_write returns [] when given no files."""
    llm = MagicMock()
    llm.model = "gpt-4.1"
    llm.supports_tools.return_value = False
    agent = BaseAgent(model="gpt-4.1", llm=llm)
    assert agent._after_write([]) == []


def test_after_write_ignores_non_py_files(tmp_path):
    """_after_write silently ignores non-Python files."""
    f = tmp_path / "script.js"
    f.write_text("function big() {}\n")
    llm = MagicMock()
    llm.model = "gpt-4.1"
    llm.supports_tools.return_value = False
    agent = BaseAgent(model="gpt-4.1", llm=llm)
    assert agent._after_write([f]) == []


def test_after_write_returns_empty_on_validation_error(tmp_path):
    """_after_write returns [] and does not raise when validator errors."""
    from unittest.mock import patch
    f = tmp_path / "any.py"
    f.write_text("def f(): pass\n")
    llm = MagicMock()
    llm.model = "gpt-4.1"
    llm.supports_tools.return_value = False
    agent = BaseAgent(model="gpt-4.1", llm=llm)
    with patch("tools.fn_map.validate_function_sizes", side_effect=RuntimeError("boom")):
        result = agent._after_write([f])
    assert result == []
