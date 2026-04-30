"""Tests for watcher / main.py installing the LLM pool from config."""
from llm_pool import LLMPoolManager, get_pool, set_pool


def test_install_pool_from_config():
    """Helper sets up the global pool from a config dict."""
    from watcher import install_llm_pool_from_config

    set_pool(None)
    install_llm_pool_from_config({"llm": {"pools": {"ollama": 4, "openai": 12}}})
    pool = get_pool()
    assert pool.limit_for("ollama") == 4
    assert pool.limit_for("openai") == 12
    set_pool(None)


def test_install_pool_handles_missing_section():
    """No llm.pools key — defaults are used."""
    from watcher import install_llm_pool_from_config

    set_pool(None)
    install_llm_pool_from_config({})
    pool = get_pool()
    assert pool.limit_for("ollama") == 1  # default
    assert pool.limit_for("openai") == 5  # default
    set_pool(None)
