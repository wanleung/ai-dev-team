# Streaming for Non-Ollama Backends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add streaming support to `OpenAICompatibleBackend` so all OAI-compatible backends (especially `opencode_go`) avoid Cloudflare 524 timeouts on long responses.

**Architecture:** Add `stream: bool` param to `OpenAICompatibleBackend` with a `_stream_call()` method. `OllamaBackend` is refactored to inherit that method instead of duplicating it. `OpenCodeGoBackend` defaults to `stream=True`. Wire the new `opencode_go_stream` config key through `BaseAgent` → `Orchestrator` → `config.yaml`.

**Tech Stack:** Python, OpenAI SDK (`openai.OpenAI`), pytest

---

## File Map

| File | Change |
|---|---|
| `agents/backends/base.py` | Add `stream` param + `_stream_call()` to `OpenAICompatibleBackend` |
| `agents/backends/ollama.py` | Remove duplicated `_stream_call()` + `call()`; pass `stream=` to super |
| `agents/backends/opencode_go.py` | Add `stream: bool = True`; pass to `OpenAICompatibleBackend` |
| `agents/base_agent.py` | Add `opencode_go_stream: bool = True`; wire to `_build_backend()` |
| `orchestrator.py` | Add `opencode_go_stream` to params, `agent_kwargs`, `_llm_cfg`, `from_config()`, `_build_factory_cfg_and_create()` |
| `config.yaml` | Add `opencode_go_stream: true` under `llm:` |
| `tests/test_backend_opencode_zen_go.py` | Add 3 streaming tests for `OpenCodeGoBackend` |
| `tests/test_backend_ollama.py` | Add test verifying `OllamaBackend` still streams via base class |

---

### Task 1: Add `stream` param and `_stream_call()` to `OpenAICompatibleBackend`

**Files:**
- Modify: `agents/backends/base.py`
- Test: `tests/test_backend_ollama.py` (existing streaming test must still pass)

- [ ] **Step 1: Write a failing test for `OpenAICompatibleBackend._stream_call()`**

Add to `tests/test_backend_ollama.py`:

```python
def test_base_stream_call_assembles_chunks():
    """OpenAICompatibleBackend._stream_call() collects chunks into a string."""
    from agents.backends.base import OpenAICompatibleBackend
    from unittest.mock import MagicMock

    chunk1 = MagicMock(choices=[MagicMock(delta=MagicMock(content="Hel"))])
    chunk2 = MagicMock(choices=[MagicMock(delta=MagicMock(content="lo"))])
    chunk3 = MagicMock(choices=[MagicMock(delta=MagicMock(content=None))])  # None delta skipped

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk3])

    b = OpenAICompatibleBackend(model="gpt-4.1", client=mock_client, stream=True)
    result = b._stream_call([{"role": "user", "content": "hi"}])
    assert result == "Hello"
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs.get("stream") is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/wanleung/Projects/ai-software-house
source ../../venv/bin/activate
pytest tests/test_backend_ollama.py::test_base_stream_call_assembles_chunks -v
```

Expected: FAIL — `OpenAICompatibleBackend.__init__` has no `stream` param, `_stream_call` does not exist.

- [ ] **Step 3: Add `stream` param, `self._stream`, and `_stream_call()` to `OpenAICompatibleBackend`**

In `agents/backends/base.py`, update `OpenAICompatibleBackend.__init__` to add `stream: bool = False` as the last parameter and store it:

```python
def __init__(
    self,
    model: str,
    client,  # openai.OpenAI instance
    inter_call_delay: int = 0,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_BASE_DELAY,
    stream: bool = False,
) -> None:
    self.model = model
    self._client = client
    self._inter_call_delay = inter_call_delay
    self._max_retries = max_retries
    self._retry_delay = retry_delay
    self._stream = stream
```

Add `_stream_call()` method directly after `_pre_call()` (before `call()`):

```python
def _stream_call(self, messages: list[dict]) -> str:
    """Collect a streaming response into a single string.

    Args:
        messages: Full message list in OpenAI chat format.

    Returns:
        Assembled and post-processed assistant reply text.
    """
    if self._inter_call_delay > 0:
        time.sleep(self._inter_call_delay)

    def _collect(stream) -> str:
        collected = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                collected += delta
        return collected

    reply = _retry_with_backoff(
        lambda: _collect(
            self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                stream=True,
                **self._extra_body(),
            )
        ),
        max_retries=self._max_retries,
        base_delay=self._retry_delay,
    )
    return self._post_process(reply)
```

Update `call()` to dispatch to `_stream_call()` when `self._stream` is True:

```python
def call(self, messages: list[dict]) -> str:
    self._pre_call()
    if self._stream:
        return self._stream_call(messages)
    if self._inter_call_delay > 0:
        time.sleep(self._inter_call_delay)
    response = _retry_with_backoff(
        lambda: self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            **self._extra_body(),
        ),
        max_retries=self._max_retries,
        base_delay=self._retry_delay,
    )
    return self._post_process(response.choices[0].message.content or "")
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
pytest tests/test_backend_ollama.py::test_base_stream_call_assembles_chunks -v
```

Expected: PASS

- [ ] **Step 5: Run existing backend tests to confirm no regression**

```bash
pytest tests/test_backend_ollama.py -v
```

Expected: All existing tests PASS (OllamaBackend still has its own `_stream_call` at this point — Task 2 removes it).

- [ ] **Step 6: Commit**

```bash
git add agents/backends/base.py tests/test_backend_ollama.py
git commit -m "feat: add stream param and _stream_call() to OpenAICompatibleBackend

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Refactor `OllamaBackend` to inherit streaming from base class

**Files:**
- Modify: `agents/backends/ollama.py`
- Test: `tests/test_backend_ollama.py` (existing tests must all pass)

- [ ] **Step 1: Remove `_stream_call()` and `call()` from `OllamaBackend`; pass `stream=stream` to super**

In `agents/backends/ollama.py`, replace the `super().__init__()` call to add `stream=stream`:

```python
super().__init__(
    model=model.removeprefix("ollama/"),
    client=client,
    inter_call_delay=inter_call_delay,
    max_retries=max_retries,
    retry_delay=retry_delay,
    stream=stream,
)
```

Remove the entire `call()` method (lines 87–102):

```python
# DELETE THIS METHOD ENTIRELY:
def call(self, messages: list[dict]) -> str:
    """Send messages to Ollama and return the assistant reply.
    ...
    """
    self._pre_call()
    if self._stream:
        return self._stream_call(messages)
    return super().call(messages)
```

Remove the entire `_stream_call()` method (lines 104–137):

```python
# DELETE THIS METHOD ENTIRELY:
def _stream_call(self, messages: list[dict]) -> str:
    """Collect a streaming response from Ollama into a single string.
    ...
    """
    ...
```

After this change, `OllamaBackend` should have only: `__init__`, `_extra_body()`, `_post_process()`.

- [ ] **Step 2: Run all Ollama backend tests**

```bash
pytest tests/test_backend_ollama.py tests/test_ollama.py -v
```

Expected: All tests PASS. `test_ollama_call_streaming` and `test_ollama_call_uses_streaming` now exercise the base class `_stream_call()`.

- [ ] **Step 3: Commit**

```bash
git add agents/backends/ollama.py
git commit -m "refactor: OllamaBackend inherits _stream_call() from OpenAICompatibleBackend

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Add `stream: bool = True` to `OpenCodeGoBackend`

**Files:**
- Modify: `agents/backends/opencode_go.py`
- Test: `tests/test_backend_opencode_zen_go.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_backend_opencode_zen_go.py`:

```python
def test_opencode_go_default_stream_true():
    """OpenCodeGoBackend (non-MiniMax) has _oai_backend._stream=True by default."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeGoBackend(model="opencode-go/kimi-k2.5")
    assert b._oai_backend._stream is True


def test_opencode_go_stream_false_disables_streaming():
    """OpenCodeGoBackend with stream=False has _oai_backend._stream=False."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeGoBackend(model="opencode-go/kimi-k2.5", stream=False)
    assert b._oai_backend._stream is False


def test_opencode_go_call_streams_when_enabled():
    """call() passes stream=True to OAI client when streaming is enabled."""
    from agents.backends.opencode_go import OpenCodeGoBackend
    chunk1 = MagicMock(choices=[MagicMock(delta=MagicMock(content="Hello"))])
    chunk2 = MagicMock(choices=[MagicMock(delta=MagicMock(content=" world"))])
    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])
        mock_oai.return_value = mock_client
        with patch.dict(os.environ, {"OPENCODE_ZEN_API_KEY": "key_test"}):
            b = OpenCodeGoBackend(model="opencode-go/kimi-k2.5", stream=True)
    result = b.call([{"role": "user", "content": "hi"}])
    assert result == "Hello world"
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs.get("stream") is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_backend_opencode_zen_go.py::test_opencode_go_default_stream_true \
       tests/test_backend_opencode_zen_go.py::test_opencode_go_stream_false_disables_streaming \
       tests/test_backend_opencode_zen_go.py::test_opencode_go_call_streams_when_enabled -v
```

Expected: FAIL — `OpenCodeGoBackend.__init__` has no `stream` param.

- [ ] **Step 3: Add `stream: bool = True` to `OpenCodeGoBackend.__init__` and wire it through**

In `agents/backends/opencode_go.py`, update `__init__` signature:

```python
def __init__(
    self,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    inter_call_delay: int = 0,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_BASE_DELAY,
    stream: bool = True,
) -> None:
```

Pass `stream=stream` when constructing `OpenAICompatibleBackend` (in the `else` block):

```python
else:
    if OpenAI is None:
        raise ImportError("openai package required: pip install openai")
    client = OpenAI(base_url=base, api_key=key)
    self._oai_backend = OpenAICompatibleBackend(
        model=bare_model, client=client,
        inter_call_delay=inter_call_delay, max_retries=max_retries, retry_delay=retry_delay,
        stream=stream,
    )
    self._anthropic_client = None
```

- [ ] **Step 4: Run new tests to verify they pass**

```bash
pytest tests/test_backend_opencode_zen_go.py -v
```

Expected: All tests PASS (including the 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add agents/backends/opencode_go.py tests/test_backend_opencode_zen_go.py
git commit -m "feat: OpenCodeGoBackend defaults to stream=True to prevent 524 timeouts

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Wire `opencode_go_stream` through `BaseAgent`

**Files:**
- Modify: `agents/base_agent.py`
- Test: `tests/test_opencode_go.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/test_opencode_go.py`:

```python
def test_base_agent_opencode_go_stream_default_true():
    """BaseAgent passes opencode_go_stream=True to OpenCodeGoBackend by default."""
    import importlib
    import agents.base_agent as ba
    importlib.reload(ba)

    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "key_test"}):
            agent = ba.BaseAgent(model="opencode-go/kimi-k2.5")

    assert agent._llm._oai_backend._stream is True


def test_base_agent_opencode_go_stream_false():
    """BaseAgent passes opencode_go_stream=False to OpenCodeGoBackend when set."""
    import importlib
    import agents.base_agent as ba
    importlib.reload(ba)

    with patch("agents.backends.opencode_go.OpenAI") as mock_oai:
        mock_oai.return_value = MagicMock()
        with patch.dict("os.environ", {"OPENCODE_ZEN_API_KEY": "key_test"}):
            agent = ba.BaseAgent(model="opencode-go/kimi-k2.5", opencode_go_stream=False)

    assert agent._llm._oai_backend._stream is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_opencode_go.py::test_base_agent_opencode_go_stream_default_true \
       tests/test_opencode_go.py::test_base_agent_opencode_go_stream_false -v
```

Expected: FAIL — `BaseAgent.__init__` has no `opencode_go_stream` param.

- [ ] **Step 3: Add `opencode_go_stream` to `BaseAgent.__init__` and `_build_backend()`**

In `agents/base_agent.py`, add `opencode_go_stream: bool = True` to `__init__` after the `opencode_go_base_url` parameter (around line 104):

```python
opencode_go_base_url: Optional[str] = None,
opencode_go_stream: bool = True,
nvidia_nim_api_key: Optional[str] = None,
```

Store it (around line 119, after `self._ollama_stream = ollama_stream`):

```python
self._opencode_go_stream = opencode_go_stream
```

Pass it to `_build_backend()` (around line 125):

```python
self._llm = self._build_backend(
    model=model,
    github_token=github_token,
    backend=backend,
    ollama_url=ollama_url,
    ollama_think=ollama_think,
    ollama_preserve_thinking=ollama_preserve_thinking,
    ollama_stream=ollama_stream,
    opencode_zen_api_key=opencode_zen_api_key,
    opencode_zen_base_url=opencode_zen_base_url,
    opencode_go_base_url=opencode_go_base_url,
    opencode_go_stream=opencode_go_stream,
    nvidia_nim_api_key=nvidia_nim_api_key,
    nvidia_nim_base_url=nvidia_nim_base_url,
    retry_delay=retry_delay,
    max_api_retries=max_api_retries,
    inter_call_delay=inter_call_delay,
)
```

Add `opencode_go_stream: bool` to `_build_backend()` signature (around line 223, after `opencode_go_base_url`):

```python
opencode_go_base_url: Optional[str],
opencode_go_stream: bool,
nvidia_nim_api_key: Optional[str],
```

Pass `stream=opencode_go_stream` in the `if use_opencode_go:` block (around line 266):

```python
if use_opencode_go:
    from agents.backends.opencode_go import OpenCodeGoBackend
    return OpenCodeGoBackend(
        model=model,
        api_key=opencode_zen_api_key,
        base_url=opencode_go_base_url,
        stream=opencode_go_stream,
        **common,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_opencode_go.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run full agent test suite to check for regressions**

```bash
pytest tests/test_ollama.py tests/test_backend_ollama.py tests/test_opencode_go.py tests/test_backend_opencode_zen_go.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/base_agent.py tests/test_opencode_go.py
git commit -m "feat: wire opencode_go_stream through BaseAgent

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Wire `opencode_go_stream` through `Orchestrator`

**Files:**
- Modify: `orchestrator.py`
- Test: `tests/test_ollama.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/test_ollama.py` (in the "New: ollama_think / ollama_stream config options" section):

```python
def test_orchestrator_passes_opencode_go_stream():
    """Orchestrator stores opencode_go_stream and includes it in agent_kwargs."""
    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_fake"}):
        import importlib
        import orchestrator as orch_mod
        importlib.reload(orch_mod)
        orc = orch_mod.Orchestrator(
            model="opencode-go/kimi-k2.5",
            opencode_go_stream=False,
        )
    assert orc.opencode_go_stream is False
    assert orc.agent_kwargs.get("opencode_go_stream") is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_ollama.py::test_orchestrator_passes_opencode_go_stream -v
```

Expected: FAIL — `Orchestrator.__init__` has no `opencode_go_stream` param.

- [ ] **Step 3: Add `opencode_go_stream` to `Orchestrator.__init__`**

In `orchestrator.py`, add `opencode_go_stream: bool = True` after `ollama_stream` in the `__init__` signature (around line 514):

```python
ollama_stream: bool = True,
opencode_go_stream: bool = True,
nvidia_nim_api_key: Optional[str] = None,
```

Add `self.opencode_go_stream = opencode_go_stream` after `self.ollama_stream = ollama_stream` (around line 560):

```python
self.ollama_stream = ollama_stream
self.opencode_go_stream = opencode_go_stream
```

Add to `agent_kwargs` dict (around line 595):

```python
agent_kwargs: dict = {"github_token": github_token, "ollama_url": ollama_url,
                      "ollama_api_key": ollama_api_key,
                      "ollama_think": ollama_think, "ollama_preserve_thinking": ollama_preserve_thinking,
                      "ollama_stream": ollama_stream,
                      "opencode_go_stream": opencode_go_stream,
                      "nvidia_nim_api_key": nvidia_nim_api_key,
                      "nvidia_nim_base_url": nvidia_nim_base_url,
                      "retry_delay": retry_delay, "max_api_retries": max_api_retries,
                      "inter_call_delay": inter_call_delay}
```

Add to `_llm_cfg` dict (around line 603):

```python
self._llm_cfg: dict = {
    "model": model,
    "ollama_url": ollama_url,
    "ollama_api_key": ollama_api_key,
    "ollama_think": ollama_think,
    "ollama_preserve_thinking": ollama_preserve_thinking,
    "ollama_stream": ollama_stream,
    "opencode_go_stream": opencode_go_stream,
}
```

- [ ] **Step 4: Add `opencode-go/` case to `_build_factory_cfg_and_create()`**

In `orchestrator.py`, in `_build_factory_cfg_and_create()`, add after the `elif model.startswith("nvidia-nim/"):` block (around line 813):

```python
elif model.startswith("opencode-go/"):
    factory_cfg["stream"] = cfg.get("opencode_go_stream", True)
```

The full block should read:

```python
if model.startswith("ollama/"):
    factory_cfg["ollama_url"] = cfg.get("ollama_url", "http://localhost:11434")
    factory_cfg["think"] = cfg.get("ollama_think", False)
    factory_cfg["preserve_thinking"] = cfg.get("ollama_preserve_thinking", False)
    factory_cfg["stream"] = cfg.get("ollama_stream", True)
    if cfg.get("ollama_api_key"):
        factory_cfg["api_key"] = cfg["ollama_api_key"]
elif model.startswith("nvidia-nim/"):
    if cfg.get("nvidia_nim_api_key"):
        factory_cfg["nvidia_nim_api_key"] = cfg["nvidia_nim_api_key"]
    if cfg.get("nvidia_nim_base_url"):
        factory_cfg["nvidia_nim_base_url"] = cfg["nvidia_nim_base_url"]
elif model.startswith("opencode-go/"):
    factory_cfg["stream"] = cfg.get("opencode_go_stream", True)
# All other backends use env-var auth and need no extra config keys.
```

- [ ] **Step 5: Add `opencode_go_stream` to `from_config()`**

In `orchestrator.py`, in the `return cls(...)` call inside `from_config()`, add after `ollama_stream=llm.get("ollama_stream", True)` (around line 925):

```python
ollama_stream=llm.get("ollama_stream", True),
opencode_go_stream=llm.get("opencode_go_stream", True),
```

- [ ] **Step 6: Run new test to verify it passes**

```bash
pytest tests/test_ollama.py::test_orchestrator_passes_opencode_go_stream -v
```

Expected: PASS

- [ ] **Step 7: Run broader orchestrator tests**

```bash
pytest tests/test_ollama.py tests/test_pipeline_modes.py -v 2>&1 | tail -20
```

Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py tests/test_ollama.py
git commit -m "feat: wire opencode_go_stream through Orchestrator

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Config + final test run + push

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Add `opencode_go_stream: true` to `config.yaml`**

In `config.yaml`, add after the `ollama_stream` entry (around line 92):

```yaml
  # Set to true to stream tokens over HTTP (prevents Cloudflare 524 timeouts)
  # Applies to the opencode-go backend (kimi-k2.5, qwen3.6-plus, glm-5.1, etc.)
  # MiniMax models (minimax-m2.7) use the Anthropic endpoint and are unaffected.
  opencode_go_stream: true
```

- [ ] **Step 2: Run full orchestrator test suite**

```bash
cd /home/wanleung/Projects/ai-software-house
source ../../venv/bin/activate
pytest tests/test_backend_ollama.py tests/test_ollama.py tests/test_backend_opencode_zen_go.py \
       tests/test_opencode_go.py tests/test_pipeline_modes.py tests/test_prd_design_loops.py -v 2>&1 | tail -30
```

Expected: All tests PASS.

- [ ] **Step 3: Commit and push**

```bash
git add config.yaml
git commit -m "config: add opencode_go_stream: true (prevents 524 on long responses)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

git push origin master
git push public master
```
