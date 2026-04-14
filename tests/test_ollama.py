"""Unit tests for Ollama support in ai-software-house."""
import pytest
from unittest.mock import MagicMock, patch


# ── _deep_merge ──────────────────────────────────────────────────────────────

def test_deep_merge_non_overlapping_keys():
    from orchestrator import _deep_merge
    result = _deep_merge({"a": 1}, {"b": 2})
    assert result == {"a": 1, "b": 2}


def test_deep_merge_override_scalar():
    from orchestrator import _deep_merge
    result = _deep_merge({"a": 1}, {"a": 99})
    assert result == {"a": 99}


def test_deep_merge_nested_merge():
    from orchestrator import _deep_merge
    base = {"llm": {"model": "gpt-4.1", "overrides": {"engineer": "gpt-4.1-mini"}}}
    override = {"llm": {"ollama_url": "http://10.0.0.1:11434", "overrides": {"engineer": "ollama/qwen2.5-coder"}}}
    result = _deep_merge(base, override)
    assert result["llm"]["model"] == "gpt-4.1"
    assert result["llm"]["ollama_url"] == "http://10.0.0.1:11434"
    assert result["llm"]["overrides"]["engineer"] == "ollama/qwen2.5-coder"


def test_deep_merge_does_not_mutate_base():
    from orchestrator import _deep_merge
    base = {"a": {"b": 1}}
    _deep_merge(base, {"a": {"c": 2}})
    assert base == {"a": {"b": 1}}


# ── _is_ollama_model ─────────────────────────────────────────────────────────

def test_is_ollama_model_with_prefix():
    from agents.base_agent import _is_ollama_model
    assert _is_ollama_model("ollama/llama3.2") is True
    assert _is_ollama_model("ollama/qwen2.5-coder") is True


def test_is_ollama_model_without_prefix():
    from agents.base_agent import _is_ollama_model
    assert _is_ollama_model("openai/gpt-4.1") is False
    assert _is_ollama_model("claude-3-5-sonnet-20241022") is False
    assert _is_ollama_model("gpt-4o") is False


# ── BaseAgent Ollama backend ──────────────────────────────────────────────────

def test_base_agent_ollama_backend_sets_api_model():
    """BaseAgent strips 'ollama/' prefix and stores bare model name."""
    with patch("agents.base_agent.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        from agents.base_agent import BaseAgent
        agent = BaseAgent(model="ollama/llama3.2", ollama_url="http://localhost:11434")
        assert agent._backend == "ollama"
        assert agent._api_model == "llama3.2"


def test_base_agent_ollama_client_uses_ollama_url():
    """BaseAgent initialises OpenAI client with Ollama base_url."""
    with patch("agents.base_agent.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        from agents.base_agent import BaseAgent
        agent = BaseAgent(model="ollama/llama3.2", ollama_url="http://10.0.0.1:11434")
        mock_openai_cls.assert_called_once_with(
            base_url="http://10.0.0.1:11434/v1",
            api_key="ollama",
        )


def test_base_agent_github_models_api_model_unchanged():
    """GitHub Models backend: _api_model is the full model string."""
    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_fake"}):
        import importlib
        import agents.base_agent as ba_module
        importlib.reload(ba_module)
        agent = ba_module.BaseAgent(model="openai/gpt-4.1")
        assert agent._backend == "github_models"
        assert agent._api_model == "openai/gpt-4.1"


def test_base_agent_ollama_url_trailing_slash_normalised():
    """Trailing slash in ollama_url is stripped to avoid double-slash in base_url."""
    with patch("agents.base_agent.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        from agents.base_agent import BaseAgent
        BaseAgent(model="ollama/llama3.2", ollama_url="http://localhost:11434/")
        mock_openai_cls.assert_called_once_with(
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )


# ── Orchestrator wiring ───────────────────────────────────────────────────────

def test_orchestrator_init_passes_ollama_url_to_agent_kwargs():
    """Orchestrator.__init__ includes ollama_url in agent_kwargs."""
    from orchestrator import Orchestrator
    orc = Orchestrator(
        github_token="ghp_fake",
        ollama_url="http://10.0.0.1:11434",
    )
    assert orc.agent_kwargs.get("ollama_url") == "http://10.0.0.1:11434"


def test_orchestrator_from_config_reads_ollama_url(tmp_path):
    """from_config() reads llm.ollama_url from YAML and passes to Orchestrator."""
    from orchestrator import Orchestrator
    import yaml
    cfg = {
        "project": {"name": "test", "description": "desc", "requirements": []},
        "github": {"owner": "org", "repo": "", "branch": "main"},
        "llm": {"model": "ollama/llama3.2", "ollama_url": "http://10.0.0.1:11434"},
        "pipeline": {"stages": []},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    orc = Orchestrator.from_config(str(config_path))
    assert orc.agent_kwargs.get("ollama_url") == "http://10.0.0.1:11434"
