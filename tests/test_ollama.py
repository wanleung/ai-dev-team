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
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        from agents.base_agent import BaseAgent
        agent = BaseAgent(model="ollama/llama3.2", ollama_url="http://localhost:11434")
        assert agent._backend == "ollama"
        assert agent._api_model == "llama3.2"


def test_base_agent_ollama_client_uses_ollama_url():
    """BaseAgent initialises OpenAI client with Ollama base_url."""
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        from agents.base_agent import BaseAgent
        agent = BaseAgent(model="ollama/llama3.2", ollama_url="http://10.0.0.1:11434")
        call_kwargs = mock_openai_cls.call_args.kwargs
        assert call_kwargs["base_url"] == "http://10.0.0.1:11434/v1"
        assert call_kwargs["api_key"] == "ollama"


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
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        from agents.base_agent import BaseAgent
        BaseAgent(model="ollama/llama3.2", ollama_url="http://localhost:11434/")
        call_kwargs = mock_openai_cls.call_args.kwargs
        assert call_kwargs["base_url"] == "http://localhost:11434/v1"
        assert call_kwargs["api_key"] == "ollama"


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


def test_orchestrator_from_config_default_ollama_url(tmp_path):
    """from_config() uses default ollama_url when key is absent from YAML."""
    from orchestrator import Orchestrator
    import yaml
    cfg = {
        "project": {"name": "test", "description": "desc", "requirements": []},
        "github": {"owner": "org", "repo": "", "branch": "main"},
        "llm": {"model": "gpt-4.1"},  # no ollama_url key
        "pipeline": {"stages": []},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    orc = Orchestrator.from_config(str(config_path))
    assert orc.agent_kwargs.get("ollama_url") == "http://localhost:11434"


def test_from_config_loads_config_local_yaml(tmp_path):
    """config.local.yaml is deep-merged over config.yaml when present."""
    import yaml
    from orchestrator import Orchestrator

    base_cfg = {
        "project": {"name": "test", "description": "desc", "requirements": []},
        "github": {"owner": "org", "repo": "", "branch": "main"},
        "llm": {"model": "gpt-4.1"},
        "pipeline": {"stages": []},
    }
    local_cfg = {
        "llm": {"ollama_url": "http://10.100.1.30:11434"},
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(base_cfg))
    (tmp_path / "config.local.yaml").write_text(yaml.dump(local_cfg))

    orc = Orchestrator.from_config(str(tmp_path / "config.yaml"))
    assert orc.agent_kwargs["ollama_url"] == "http://10.100.1.30:11434"


# ── Ollama streaming + thinking suppression tests ────────────────────────────

def _make_chunk(content):
    """Helper to create a fake streaming chunk."""
    chunk = MagicMock()
    chunk.choices[0].delta.content = content
    return chunk


def test_ollama_call_uses_streaming():
    """call() passes stream=True to chat.completions.create for Ollama backend."""
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        # Return an iterator of chunks
        mock_client.chat.completions.create.return_value = iter([
            _make_chunk("Hello"),
            _make_chunk(" world"),
        ])

        import importlib
        import agents.base_agent as ba
        importlib.reload(ba)

        agent = ba.BaseAgent(model="ollama/qwen3", ollama_url="http://10.0.0.1:11434")
        agent.client = mock_client
        result = agent.call("Say hi")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("stream") is True
        assert result == "Hello world"


def test_ollama_think_tags_stripped():
    """call() strips <think>...</think> blocks from Ollama streaming responses."""
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([
            _make_chunk("<think>some internal reasoning\n"),
            _make_chunk("more reasoning</think>\n"),
            _make_chunk("Actual answer"),
        ])

        import importlib
        import agents.base_agent as ba
        importlib.reload(ba)

        agent = ba.BaseAgent(model="ollama/qwen3", ollama_url="http://10.0.0.1:11434")
        agent.client = mock_client
        result = agent.call("Think hard")

        assert result == "Actual answer"
        assert "<think>" not in result


def test_ollama_extra_body_think_false():
    """call() passes extra_body={'think': False} for Ollama backend calls."""
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([
            _make_chunk("Answer"),
        ])

        import importlib
        import agents.base_agent as ba
        importlib.reload(ba)

        agent = ba.BaseAgent(model="ollama/qwen3", ollama_url="http://10.0.0.1:11434")
        agent.client = mock_client
        agent.call("Test")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("extra_body") == {"think": False}


def test_non_ollama_not_streaming():
    """call() does NOT use stream=True for non-Ollama (github_models) backend."""
    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_fake"}):
        import importlib
        import agents.base_agent as ba
        importlib.reload(ba)

        agent = ba.BaseAgent(model="openai/gpt-4.1")

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Response"
        agent.client = MagicMock()
        agent.client.chat.completions.create.return_value = mock_response

        agent.call("Hello")

        call_kwargs = agent.client.chat.completions.create.call_args.kwargs
        # stream should not be True (either absent or False)
        assert not call_kwargs.get("stream")


def test_ollama_no_timeout():
    """Ollama client is created with no read timeout (timeout.read is None)."""
    import httpx
    import os as _os
    import importlib
    import agents.base_agent as ba

    _os.environ.pop("OLLAMA_TIMEOUT", None)
    importlib.reload(ba)

    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = MagicMock()
        ba.BaseAgent(model="ollama/qwen3", ollama_url="http://10.0.0.1:11434")
        call_kwargs = mock_openai_cls.call_args.kwargs
        timeout = call_kwargs.get("timeout")
        assert timeout is not None, "timeout kwarg should be passed to OpenAI client"
        # With no OLLAMA_TIMEOUT set, read timeout should be None (unlimited)
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.read is None


# ── New: ollama_think / ollama_stream config options ─────────────────────────

def test_ollama_stream_disabled_no_stream_kwarg():
    """call() does NOT pass stream=True when ollama_stream=False."""
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Answer"
        mock_client.chat.completions.create.return_value = mock_response

        import importlib
        import agents.base_agent as ba
        importlib.reload(ba)

        agent = ba.BaseAgent(
            model="ollama/qwen3",
            ollama_url="http://10.0.0.1:11434",
            ollama_stream=False,
        )
        agent.client = mock_client
        agent.call("Test")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("stream") is not True


def test_ollama_think_enabled_no_extra_body():
    """call() does NOT pass extra_body={'think': False} when ollama_think=True."""
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([
            _make_chunk("Answer"),
        ])

        import importlib
        import agents.base_agent as ba
        importlib.reload(ba)

        agent = ba.BaseAgent(
            model="ollama/qwen3",
            ollama_url="http://10.0.0.1:11434",
            ollama_think=True,
        )
        agent.client = mock_client
        agent.call("Test")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        extra_body = call_kwargs.get("extra_body", {})
        assert extra_body.get("think") is not False


def test_ollama_think_disabled_extra_body_false():
    """call() passes extra_body={'think': False} when ollama_think=False (default)."""
    with patch("agents.backends.ollama.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter([
            _make_chunk("Answer"),
        ])

        import importlib
        import agents.base_agent as ba
        importlib.reload(ba)

        agent = ba.BaseAgent(
            model="ollama/qwen3",
            ollama_url="http://10.0.0.1:11434",
            ollama_think=False,  # default — suppress thinking
        )
        agent.client = mock_client
        agent.call("Test")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("extra_body") == {"think": False}


def test_orchestrator_passes_ollama_think_stream():
    """Orchestrator passes ollama_think and ollama_stream through to agent_kwargs."""
    from orchestrator import Orchestrator

    orc = Orchestrator(
        github_token="ghp_fake",
        ollama_url="http://10.0.0.1:11434",
        ollama_think=True,
        ollama_stream=False,
    )
    assert orc.agent_kwargs.get("ollama_think") is True
    assert orc.agent_kwargs.get("ollama_stream") is False
    assert orc.ollama_think is True
    assert orc.ollama_stream is False


# ── Per-agent ollama_think / ollama_stream overrides ─────────────────────────

def test_model_override_dict_form_model():
    """Dict override: architect gets the dict's model and ollama_think values.

    After the _mk() refactor, per-agent ollama_think overrides are baked into the
    LLM backend (backend._think) rather than the agent's legacy _ollama_think
    attribute.  The agent-level attribute still reflects the *global* setting
    passed via agent_kwargs; the per-agent value is verified via the backend.
    """
    from orchestrator import Orchestrator

    orc = Orchestrator(
        model="ollama/llama4",
        model_overrides={
            "architect": {
                "model": "ollama/qwen3.6",
                "ollama_think": True,
            }
        },
        ollama_think=False,
        ollama_stream=True,
    )
    # Model prefix is stripped by BaseAgent; we verify the Orchestrator resolves
    # the dict's model key, i.e., the agent was NOT created with the global model.
    # We do that by checking the _api_model stored on the agent instance.
    assert orc.architect._api_model == "qwen3.6"
    # ollama_think=True was specified in the dict override — it is baked into the
    # LLM backend (_think), not the legacy agent-level attribute.
    assert orc.architect._llm._think is True


def test_model_override_dict_form_inherits_global():
    """Dict override without ollama_think key inherits global ollama_think."""
    from orchestrator import Orchestrator

    orc = Orchestrator(
        model="ollama/llama4",
        model_overrides={
            "engineer": {
                "model": "ollama/qwen2.5:latest",
                # ollama_think intentionally absent → should inherit global
            }
        },
        ollama_think=True,   # global default
        ollama_stream=False,
    )
    # No ollama_think in override → falls back to global True
    assert orc.engineer._ollama_think is True
    # No ollama_stream in override → falls back to global False
    assert orc.engineer._ollama_stream is False


def test_model_override_string_form_unchanged():
    """String override still works and agent inherits global ollama_think/ollama_stream."""
    from orchestrator import Orchestrator

    orc = Orchestrator(
        model="ollama/llama4",
        model_overrides={"qa_engineer": "ollama/qwen3.6"},
        ollama_think=False,
        ollama_stream=True,
    )
    assert orc.qa._api_model == "qwen3.6"
    assert orc.qa._ollama_think is False
    assert orc.qa._ollama_stream is True


def test_model_helper_dict_returns_model_key():
    """_model() returns the 'model' key from a dict override."""
    from orchestrator import Orchestrator

    orc = Orchestrator(
        model="ollama/llama4",
        model_overrides={
            "engineer": {"model": "ollama/qwen2.5", "ollama_think": True}
        },
    )
    # Agent was instantiated with ollama/qwen2.5; BaseAgent strips prefix → qwen2.5
    assert orc.engineer._api_model == "qwen2.5"


def test_model_helper_dict_no_model_key_falls_back():
    """_model() falls back to global model when dict override has no 'model' key."""
    from orchestrator import Orchestrator

    orc = Orchestrator(
        model="ollama/llama4",
        model_overrides={
            "pm_reviewer": {"ollama_think": True}  # no 'model' key
        },
    )
    # Should fall back to the global model "ollama/llama4" → api_model "llama4"
    assert orc.pm_reviewer._api_model == "llama4"


def test_orchestrator_passes_opencode_stream():
    """Orchestrator stores opencode_stream and passes it through to agent_kwargs."""
    from orchestrator import Orchestrator

    orc = Orchestrator(
        github_token="ghp_fake",
        opencode_stream=False,
    )
    assert orc.opencode_stream is False
    assert orc.agent_kwargs.get("opencode_stream") is False


@pytest.mark.parametrize("model_prefix", [
    "opencode-go/",
    "opencode-zen/",
])
def test_opencode_stream_reaches_backend_via_factory(model_prefix):
    """Verifies _build_factory_cfg_and_create() translates opencode_stream→stream.
    
    This test ensures that when the orchestrator's _build_factory_cfg_and_create()
    method is called with an opencode-go or opencode-zen model, it correctly:
    1. Translates opencode_stream to stream in factory_cfg
    2. Does NOT pass opencode_stream to the backend factory
    
    The test patches _make_single_backend to capture what config is passed to it,
    verifying the translation happened at the orchestrator level, not elsewhere.
    """
    from orchestrator import Orchestrator
    from unittest.mock import MagicMock, patch
    
    # Create an orchestrator instance with opencode_stream=False
    orc = Orchestrator(
        github_token="ghp_fake",
        opencode_stream=False,
    )
    
    # Prepare the config dict that would come from YAML/orchestrator init
    cfg = {
        "model": f"{model_prefix}gpt-4.1",
        "opencode_stream": False,
    }
    
    # Patch _make_single_backend to capture what factory_cfg is passed to it
    with patch("agents.backends.factory._make_single_backend") as mock_factory:
        mock_backend = MagicMock()
        mock_factory.return_value = mock_backend
        
        # Call the real method that should perform the translation
        orc._build_factory_cfg_and_create(cfg)
        
        # Verify _make_single_backend was called with stream=False, NOT opencode_stream
        mock_factory.assert_called_once()
        factory_cfg = mock_factory.call_args[0][0]  # First positional arg
        
        # Assert that stream=False was passed (the translation happened)
        assert factory_cfg.get("stream") is False, \
            f"Expected stream=False in factory_cfg for {model_prefix}"
        
        # Assert that opencode_stream key was removed (not passed to backend)
        assert "opencode_stream" not in factory_cfg, \
            f"opencode_stream should not appear in factory_cfg for {model_prefix}"
        
        # Assert the model was preserved
        assert factory_cfg.get("model") == f"{model_prefix}gpt-4.1"


