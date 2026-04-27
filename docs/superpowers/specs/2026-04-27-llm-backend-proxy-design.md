# LLM Backend Proxy — Design Spec

**Date:** 2026-04-27  
**Status:** Approved, pending implementation  
**Branch:** `feature/llm-backend-proxy`  
**PR required:** Yes — merge to master after all tests pass

---

## Problem

`agents/base_agent.py` (905 lines) mixes agent logic with LLM routing logic for 8 backends. Every new backend feature (e.g. `preserve_thinking`) requires editing `__init__`, `call()`, `call_with_tools()`, and adding more `if self._backend ==` branches. There is no automatic failover if a backend is unreachable.

---

## Goals

1. Extract all LLM backend code into `agents/backends/` — one class per backend.
2. Add a `FallbackLLMBackend` that auto-switches to the next backend on connection errors, replaying conversation history.
3. Print a visible `⚠️` notice when a fallback occurs.
4. Support global fallback config + per-agent override.
5. No change to existing `config.yaml` keys or public agent APIs.

---

## Architecture

### File Structure

```
agents/
  backends/
    __init__.py          # exports create_backend()
    base.py              # LLMBackend abstract base class
    factory.py           # create_backend(cfg, **auth) → LLMBackend | FallbackLLMBackend
    fallback.py          # FallbackLLMBackend
    github_models.py
    ollama.py            # includes think / preserve_thinking / stream logic
    anthropic.py
    copilot.py           # includes session token refresh
    nvidia_nim.py
    opencode.py          # subprocess CLI
    opencode_zen.py
    opencode_go.py
  base_agent.py          # agent logic only: system prompt, history, tools
```

`base_agent.py` shrinks from ~905 lines to ~500 lines. Backend detection and client initialisation are removed entirely.

---

## `LLMBackend` Interface

```python
class LLMBackend(ABC):
    model: str  # resolved model name (without prefix)

    @abstractmethod
    def call(self, messages: list[dict]) -> str:
        """Send a chat message list and return the assistant reply."""

    @abstractmethod
    def call_with_tools(self, messages: list[dict], tools: ToolRegistry) -> str:
        """Send messages with tool schemas, execute tools, return final reply."""

    def supports_tools(self) -> bool:
        """Return False for backends that cannot use function calling."""
        return True
```

`BaseAgent` builds the `messages` list (system prompt + history + new message) and passes it to `self._llm.call(messages)`. It no longer routes by backend name.

Backends that don't support tools (`opencode`, `anthropic`) return `False` from `supports_tools()`. `BaseAgent.call_with_tools()` raises `NotImplementedError` with a clear message in that case.

---

## `FallbackLLMBackend`

```python
class FallbackLLMBackend(LLMBackend):
    def __init__(self, backends: list[LLMBackend]): ...

    def call(self, messages: list[dict]) -> str:
        for i, backend in enumerate(self.backends):
            try:
                return backend.call(messages)
            except FALLBACK_ERRORS as exc:
                if i == len(self.backends) - 1:
                    raise
                print(f"⚠️  {backend.model} unreachable ({exc}), "
                      f"falling back to {self.backends[i+1].model}")
```

`call_with_tools` follows the same pattern.

**Triggers fallback (transient/infrastructure errors):**
- `ConnectionError`, `httpx.ConnectError`, `httpx.TimeoutException`
- `openai.APIConnectionError`, `openai.APITimeoutError`
- HTTP 503

**Does NOT trigger fallback (user/config errors):**
- `openai.AuthenticationError` (wrong API key)
- `openai.BadRequestError` (bad prompt)
- HTTP 400, 401, 422

**History replay:** because `BaseAgent` always passes the full `messages` list, the fallback backend receives complete context automatically.

---

## Config

### Global fallback chain

```yaml
llm:
  model: "ollama/qwen3.6"
  fallbacks:
    - model: "copilot/gpt-4.1"
    - model: "github_models/gpt-4o-mini"
```

### Per-agent override (overrides global fallbacks entirely if present)

```yaml
llm:
  overrides:
    architect:
      model: "ollama/qwen3.6"
      ollama_think: true
      fallbacks:
        - model: "copilot/claude-sonnet-4.6"
    junior_engineer:
      model: "ollama/qwen2.5-coder:7b"
      # no fallbacks — inherits global
```

---

## Orchestrator Changes

`Orchestrator` keeps all existing `__init__` kwargs for backward compatibility. Internally they are converted to backend config dicts and passed to `create_backend()`:

```python
def _make_backend(agent_name: str) -> LLMBackend:
    override = model_overrides.get(agent_name, {})
    cfg = {**global_llm_cfg, **override}  # per-agent wins
    return create_backend(cfg, github_token=token)
```

If `cfg` has no `fallbacks` key, `create_backend` returns a plain `LLMBackend`. If `fallbacks` is present, it returns a `FallbackLLMBackend`.

---

## Error Handling

| Error type | Behaviour |
|---|---|
| Connection / timeout | Print `⚠️` warning, try next backend |
| Auth error | Raise immediately (retrying another key won't help) |
| All backends exhausted | Re-raise the last error |
| Backend doesn't support tools | Raise `NotImplementedError` with backend name |

---

## Testing

- Unit tests for each backend class (mocked HTTP)
- Unit tests for `FallbackLLMBackend`: verify switch on `ConnectionError`, no switch on `AuthenticationError`, history replay on fallback, exhaustion raises
- All existing tests in `tests/` must continue to pass
- `conftest.py` updated to construct agents via `LLMBackend` mocks instead of patching `self.client`

---

## PR Strategy

1. Work on branch `feature/llm-backend-proxy` in `ai-software-house`
2. All existing tests pass + new backend/fallback tests added
3. Open PR to `master` for review before merging
4. After merge, sync to `ai-dev-team` via standard upstream merge
