"""Unit tests for OpenCode CLI backend in ai-software-house."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest


# ── _is_opencode_model ────────────────────────────────────────────────────────

def test_is_opencode_model_with_prefix():
    from agents.base_agent import _is_opencode_model
    assert _is_opencode_model("opencode/anthropic/claude-sonnet-4-5") is True
    assert _is_opencode_model("opencode/openai/gpt-4o") is True
    assert _is_opencode_model("opencode/google/gemini-2.0-flash") is True


def test_is_opencode_model_without_prefix():
    from agents.base_agent import _is_opencode_model
    assert _is_opencode_model("openai/gpt-4.1") is False
    assert _is_opencode_model("claude-3-5-sonnet-20241022") is False
    assert _is_opencode_model("ollama/llama3.2") is False


# ── BaseAgent opencode backend initialisation ─────────────────────────────────

def test_base_agent_opencode_backend_detected_from_prefix():
    """BaseAgent auto-detects 'opencode' backend from model prefix."""
    from agents.base_agent import BaseAgent
    agent = BaseAgent(model="opencode/anthropic/claude-sonnet-4-5")
    assert agent._backend == "opencode"


def test_base_agent_opencode_strips_prefix_from_api_model():
    """BaseAgent strips 'opencode/' prefix, storing the remainder for the CLI --model flag."""
    from agents.base_agent import BaseAgent
    agent = BaseAgent(model="opencode/anthropic/claude-sonnet-4-5")
    assert agent._api_model == "anthropic/claude-sonnet-4-5"


def test_base_agent_opencode_no_openai_client():
    """BaseAgent does not initialise an OpenAI client for the opencode backend."""
    from agents.base_agent import BaseAgent
    agent = BaseAgent(model="opencode/openai/gpt-4o")
    assert agent.client is None


def test_base_agent_opencode_explicit_backend_override():
    """Explicit backend='opencode' works without the model prefix."""
    from agents.base_agent import BaseAgent
    agent = BaseAgent(model="anthropic/claude-sonnet-4-5", backend="opencode")
    assert agent._backend == "opencode"
    assert agent._api_model == "anthropic/claude-sonnet-4-5"


# ── _call_opencode subprocess behaviour ───────────────────────────────────────

def _make_agent(model="opencode/anthropic/claude-sonnet-4-5"):
    from agents.base_agent import BaseAgent
    return BaseAgent(model=model)


def test_call_opencode_runs_correct_command():
    """_call_opencode invokes `opencode run --model <provider/model> <prompt>`."""
    agent = _make_agent()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Here is the design."
    mock_result.stderr = ""

    with patch("agents.backends.opencode.subprocess.run", return_value=mock_result) as mock_run:
        agent._call_opencode("Design the system")

    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "opencode"
    assert call_args[1] == "run"
    assert call_args[2] == "--model"
    assert call_args[3] == "anthropic/claude-sonnet-4-5"


def test_call_opencode_embeds_system_prompt():
    """_call_opencode prepends the system role prompt to the combined message."""
    from agents.base_agent import BaseAgent
    agent = BaseAgent(model="opencode/openai/gpt-4o")
    agent.system_prompt = "You are a senior architect."

    mock_result = MagicMock(returncode=0, stdout="Design done.", stderr="")
    with patch("agents.backends.opencode.subprocess.run", return_value=mock_result) as mock_run:
        agent._call_opencode("Build a REST API")

    combined_prompt = mock_run.call_args[0][0][-1]
    assert "[SYSTEM ROLE]" in combined_prompt
    assert "You are a senior architect." in combined_prompt
    assert "Build a REST API" in combined_prompt


def test_call_opencode_embeds_history():
    """_call_opencode includes prior conversation turns in the combined prompt."""
    agent = _make_agent()
    agent._history = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
    ]

    mock_result = MagicMock(returncode=0, stdout="Second answer.", stderr="")
    with patch("agents.backends.opencode.subprocess.run", return_value=mock_result) as mock_run:
        agent._call_opencode("Second question")

    combined_prompt = mock_run.call_args[0][0][-1]
    assert "[CONVERSATION HISTORY]" in combined_prompt
    assert "First question" in combined_prompt
    assert "First answer" in combined_prompt


def test_call_opencode_strips_ansi_codes():
    """_call_opencode strips ANSI escape sequences from terminal-formatted output."""
    agent = _make_agent()
    mock_result = MagicMock(
        returncode=0,
        stdout="\x1b[32mHere is the design.\x1b[0m",
        stderr="",
    )
    with patch("agents.backends.opencode.subprocess.run", return_value=mock_result):
        result = agent._call_opencode("Design the system")

    assert "\x1b" not in result
    assert "Here is the design." in result


def test_call_opencode_updates_history():
    """_call_opencode appends user/assistant turns to self._history."""
    agent = _make_agent()
    mock_result = MagicMock(returncode=0, stdout="Response.", stderr="")

    with patch("agents.backends.opencode.subprocess.run", return_value=mock_result):
        agent._call_opencode("Prompt text")

    assert len(agent._history) == 2
    assert agent._history[0]["role"] == "user"
    assert agent._history[0]["content"] == "Prompt text"
    assert agent._history[1]["role"] == "assistant"
    assert agent._history[1]["content"] == "Response."


def test_call_opencode_raises_on_nonzero_exit():
    """_call_opencode raises RuntimeError when opencode exits non-zero."""
    agent = _make_agent()
    mock_result = MagicMock(returncode=1, stdout="", stderr="opencode: auth error")

    with patch("agents.backends.opencode.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="opencode exited 1"):
            agent._call_opencode("Design the system", max_retries=0)


def test_call_opencode_raises_on_empty_output():
    """_call_opencode raises RuntimeError when stdout is empty."""
    agent = _make_agent()
    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with patch("agents.backends.opencode.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Empty response"):
            agent._call_opencode("Design the system", max_retries=0)


def test_call_opencode_retries_on_failure():
    """_call_opencode retries up to max_retries times on failure."""
    agent = _make_agent()
    fail_result = MagicMock(returncode=1, stdout="", stderr="transient error")
    ok_result = MagicMock(returncode=0, stdout="Success.", stderr="")

    with patch("agents.backends.opencode.subprocess.run", side_effect=[fail_result, ok_result]):
        with patch("agents.backends.opencode.time.sleep"):
            result = agent._call_opencode("Design the system", max_retries=1)

    assert result == "Success."


def test_call_opencode_uses_opencode_bin_env():
    """OPENCODE_BIN environment variable overrides the opencode binary path."""
    agent = _make_agent()
    mock_result = MagicMock(returncode=0, stdout="Response.", stderr="")

    with patch("agents.backends.opencode.subprocess.run", return_value=mock_result) as mock_run:
        with patch.dict("os.environ", {"OPENCODE_BIN": "/usr/local/bin/opencode"}):
            agent._call_opencode("Prompt")

    assert mock_run.call_args[0][0][0] == "/usr/local/bin/opencode"


# ── call() routing ────────────────────────────────────────────────────────────

def test_call_routes_to_opencode_backend():
    """BaseAgent.call() routes to _call_opencode when backend is 'opencode'."""
    agent = _make_agent()
    with patch.object(agent, "_call_opencode", return_value="mocked") as mock_oc:
        result = agent.call("Do something")
    mock_oc.assert_called_once()
    assert result == "mocked"


# ── call_with_tools restriction ───────────────────────────────────────────────

def test_call_with_tools_raises_for_opencode():
    """call_with_tools raises NotImplementedError for the opencode backend."""
    agent = _make_agent()
    tools = MagicMock()
    with pytest.raises(NotImplementedError, match="opencode"):
        agent.call_with_tools("Design", tools)
