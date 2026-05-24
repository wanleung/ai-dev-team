# Agent ≤30-Line Function Rule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the ≤30-line function rule to all agent Python files, inject a `<coding_standards>` block into 7 agent role prompts, and add a post-generation validator that uses `fn_map.py` to enforce the rule in code AI agents produce.

**Architecture:** Three independent PRs — PR-A refactors existing agent `.py` files, PR-B updates role `.md` prompt files, PR-C adds `validate_function_sizes()` to `tools/fn_map.py` and hooks it into `BaseAgent._after_write()`. PR-B must merge before PR-C.

**Tech Stack:** Python 3.11, ast module, pytest (1780 tests), `tools/fn_map.py` (existing), `roles/` directory for system prompts.

---

## File Map

### PR-A (refactor)
- Modify: `agents/base_agent.py:96-169, 234-365, 465-502, 504-550, 555-602`
- Modify: `agents/discussion_agent.py:94-157, 297-387, 431-487, 574-646`
- Modify: `agents/conflict_resolver.py:87-171`
- Modify: `agents/deploy_backends.py:114-148, 159-235, 315-410`
- Modify: `agents/engineer.py:29-305`
- Modify: `agents/qa_engineer.py:24-202`
- Modify: `agents/senior_engineer.py:18-82`
- Modify: `agents/token_ledger.py:109-249, 267-320`
- Modify: `agents/pr_proposal.py:43-279`
- Modify: `agents/pr_analyst.py:46-354`
- Modify: `agents/pr_creative.py:94-139`
- Modify: `agents/bootstrap_patterns_agent.py:36-95`
- Modify: `agents/architect.py:73-192`
- Modify: `agents/documentation_agent.py:39-139`
- Modify: `agents/news_editor.py:17-68`
- Modify: `agents/news_reviewer.py:107-158`
- Modify: `agents/news_writer.py:27-65`
- Modify: `agents/qa_planner.py:29-79`
- Modify: `agents/memory_bank_updater.py:35-73`
- Modify: `agents/product_manager.py:20-126`
- Modify: `agents/architect_reviewer.py:22-56`
- Modify: `agents/code_reviewer.py:32-67`
- Modify: `agents/pm_reviewer.py:22-56`
- Modify: `agents/deployment_tester.py:38-79, 145-177`

### PR-B (prompts)
- Modify: `roles/engineer.md`
- Modify: `roles/senior_engineer.md`
- Modify: `roles/qa_engineer.md`
- Modify: `roles/architect.md`
- Modify: `roles/conflict_resolver.md`
- Modify: `roles/code_reviewer.md`
- Modify: `roles/documentation_agent.md`

### PR-C (validator)
- Modify: `tools/fn_map.py` — add `validate_function_sizes()`
- Modify: `agents/base_agent.py` — add `_after_write()` hook
- Create: `tests/test_validate_function_sizes.py`
- Modify: `tests/test_base_agent.py` — add `_after_write` tests

---

## Refactoring Methodology (applies to all tasks in PR-A)

**Rule:** Every function body must be ≤30 lines. Count from the first line of the body to the last (inclusive) — not including the `def` line.

**Pattern:**
1. Identify the large function's responsibilities (usually 2-4 distinct concerns)
2. Extract each concern to a private helper method with a descriptive name: `_parse_xyz`, `_build_xyz`, `_validate_xyz`, `_collect_xyz`
3. Keep the public/original method as a coordinator that calls the helpers — it should become 5-15 lines
4. Each extracted helper must itself be ≤30 lines
5. Never change the public API or method signatures

**Test command:** `python -m pytest tests/ -x -q` (must pass before AND after each task)
**Violation check:** `python tools/fn_map.py --no-html` (zero violations in agents/ is the final target)

---

## PR-A: Refactor Agent Python Files

### Task 1: Baseline and branch setup

- [ ] **Step 1: Run full test suite and record baseline**

```bash
cd /home/wanleung/Projects/ai-software-house
python -m pytest tests/ -q 2>&1 | tail -3
```
Expected: `1780 passed` (or similar, note the count)

- [ ] **Step 2: Run fn_map to record current violations**

```bash
python tools/fn_map.py --no-html 2>&1 | grep -E "VIOLATION|violation|exceed" | wc -l
```
Record the number.

- [ ] **Step 3: Create PR-A branch**

```bash
git checkout -b feat/agent-30-line-refactor
```

---

### Task 2: Refactor `agents/base_agent.py`

Five violations: `_build_backend` (107 lines), `__init__` (46), `truncate_files` (43), `call_with_tools` (40), `call` (37).

**Files:**
- Modify: `agents/base_agent.py`

- [ ] **Step 1: Refactor `_build_backend` (lines 234–365, 107 body lines)**

Replace the body of `_build_backend` with three helpers. The original method becomes a 12-line coordinator:

```python
def _build_backend(
    self,
    model: str,
    github_token: Optional[str],
    backend: Optional[str],
    ollama_url: str,
    ollama_think: bool,
    ollama_preserve_thinking: bool,
    ollama_stream: bool,
    opencode_stream: bool,
    github_models_stream: bool,
    opencode_zen_api_key: Optional[str],
    opencode_zen_base_url: Optional[str],
    opencode_go_base_url: Optional[str],
    nvidia_nim_api_key: Optional[str],
    nvidia_nim_base_url: Optional[str],
    dashscope_api_key: Optional[str],
    dashscope_url: Optional[str],
    dashscope_think: bool,
    dashscope_preserve_thinking: bool,
    dashscope_stream: bool,
    retry_delay: int,
    max_api_retries: int,
    inter_call_delay: int,
) -> _LLMBackend:
    """Detect which backend to use and construct it from the supplied kwargs."""
    flags = self._resolve_backend_flags(model, backend)
    common = dict(
        inter_call_delay=inter_call_delay,
        max_retries=max_api_retries,
        retry_delay=retry_delay,
    )
    kw = dict(
        ollama_url=ollama_url, ollama_think=ollama_think,
        ollama_preserve_thinking=ollama_preserve_thinking, ollama_stream=ollama_stream,
        opencode_stream=opencode_stream, github_models_stream=github_models_stream,
        opencode_zen_api_key=opencode_zen_api_key, opencode_zen_base_url=opencode_zen_base_url,
        opencode_go_base_url=opencode_go_base_url, nvidia_nim_api_key=nvidia_nim_api_key,
        nvidia_nim_base_url=nvidia_nim_base_url, dashscope_api_key=dashscope_api_key,
        dashscope_url=dashscope_url, dashscope_think=dashscope_think,
        dashscope_preserve_thinking=dashscope_preserve_thinking, dashscope_stream=dashscope_stream,
    )
    return self._instantiate_backend(flags, model, github_token, common, kw)
```

Add `_resolve_backend_flags` immediately after `_build_backend`:

```python
def _resolve_backend_flags(self, model: str, backend: Optional[str]) -> dict[str, bool]:
    """Map model prefix / explicit backend name to boolean selection flags."""
    use_opencode_zen = (backend == "opencode_zen") or (backend is None and _is_opencode_zen_model(model))
    use_opencode_go = (backend == "opencode_go") or (backend is None and _is_opencode_go_model(model))
    use_nvidia_nim = (backend == "nvidia_nim") or (backend is None and _is_nvidia_nim_model(model))
    use_copilot = (backend == "copilot") or (backend is None and _is_copilot_model(model))
    use_dashscope = (backend == "dashscope") or (backend is None and _is_dashscope_model(model))
    no_special = not any([use_opencode_zen, use_opencode_go, use_nvidia_nim, use_copilot, use_dashscope])
    use_anthropic = (backend == "anthropic") or (backend is None and no_special and _is_anthropic_model(model))
    return {
        "use_copilot": use_copilot,
        "use_opencode_go": use_opencode_go,
        "use_opencode_zen": use_opencode_zen,
        "use_nvidia_nim": use_nvidia_nim,
        "use_opencode": (backend == "opencode") or (backend is None and _is_opencode_model(model)),
        "use_anthropic": use_anthropic,
        "use_ollama": (backend == "ollama") or (backend is None and _is_ollama_model(model)),
        "use_dashscope": use_dashscope,
    }
```

Add `_instantiate_backend` — split into three helpers (opencode group, cloud group, local group):

```python
def _instantiate_backend(
    self, flags: dict[str, bool], model: str,
    github_token: Optional[str], common: dict, kw: dict,
) -> _LLMBackend:
    """Construct the LLM backend from resolved flags and kwargs."""
    result = (
        self._try_opencode_backends(flags, model, common, kw)
        or self._try_cloud_backends(flags, model, common, kw)
        or self._try_local_backends(flags, model, common, kw)
    )
    if result is not None:
        return result
    from agents.backends.github_models import GitHubModelsBackend
    return GitHubModelsBackend(
        model=model, github_token=github_token,
        stream=kw["github_models_stream"], **common,
    )

def _try_opencode_backends(self, flags, model, common, kw) -> Optional[_LLMBackend]:
    """Return an OpenCode-family backend if flagged; None otherwise."""
    if flags["use_copilot"]:
        from agents.backends.copilot import CopilotBackend
        return CopilotBackend(model=model, **common)
    if flags["use_opencode_go"]:
        from agents.backends.opencode_go import OpenCodeGoBackend
        return OpenCodeGoBackend(model=model, api_key=kw["opencode_zen_api_key"],
            base_url=kw["opencode_go_base_url"], stream=kw["opencode_stream"], **common)
    if flags["use_opencode_zen"]:
        from agents.backends.opencode_zen import OpenCodeZenBackend
        return OpenCodeZenBackend(model=model, api_key=kw["opencode_zen_api_key"],
            base_url=kw["opencode_zen_base_url"], stream=kw["opencode_stream"], **common)
    if flags["use_opencode"]:
        from agents.backends.opencode import OpenCodeBackend
        return OpenCodeBackend(model=model)
    return None

def _try_cloud_backends(self, flags, model, common, kw) -> Optional[_LLMBackend]:
    """Return a cloud API backend (NIM, Anthropic, DashScope) if flagged; None otherwise."""
    if flags["use_nvidia_nim"]:
        from agents.backends.nvidia_nim import NvidiaNimBackend
        return NvidiaNimBackend(model=model, nvidia_nim_api_key=kw["nvidia_nim_api_key"],
            nvidia_nim_base_url=kw["nvidia_nim_base_url"], **common)
    if flags["use_anthropic"]:
        from agents.backends.anthropic import AnthropicBackend
        return AnthropicBackend(model=model, **common)
    if flags["use_dashscope"]:
        from agents.backends.dashscope import DashScopeBackend
        return DashScopeBackend(model=model, dashscope_api_key=kw["dashscope_api_key"],
            dashscope_url=kw["dashscope_url"], think=kw["dashscope_think"],
            preserve_thinking=kw["dashscope_preserve_thinking"], stream=kw["dashscope_stream"], **common)
    return None

def _try_local_backends(self, flags, model, common, kw) -> Optional[_LLMBackend]:
    """Return an Ollama backend if flagged; None otherwise."""
    if flags["use_ollama"]:
        from agents.backends.ollama import OllamaBackend
        return OllamaBackend(model=model, ollama_url=kw["ollama_url"],
            think=kw["ollama_think"], preserve_thinking=kw["ollama_preserve_thinking"],
            stream=kw["ollama_stream"], **common)
    return None
```

- [ ] **Step 2: Refactor `__init__` (lines 96–169, 46 body lines)**

Extract flag/delay assignments into a helper. `__init__` becomes the coordinator:

```python
def __init__(self, model="gpt-4.1", llm=None, github_token=None, roles_dir=None,
             backend=None, ollama_url="http://localhost:11434",
             ollama_think=False, ollama_preserve_thinking=False, ollama_stream=True,
             opencode_stream=True, github_models_stream=True, opencode_zen_api_key=None,
             opencode_zen_base_url=None, opencode_go_base_url=None,
             nvidia_nim_api_key=None, nvidia_nim_base_url=None,
             dashscope_api_key=None, dashscope_url=None, dashscope_think=False,
             dashscope_preserve_thinking=False, dashscope_stream=True,
             retry_delay=15, max_api_retries=5, inter_call_delay=0, **kwargs) -> None:
    self.model = model
    self.system_prompt = self._load_system_prompt(roles_dir)
    self._token = github_token
    self._history: list[dict] = []
    self._init_retry_settings(retry_delay, max_api_retries, inter_call_delay)
    self._init_stream_flags(ollama_think, ollama_preserve_thinking, ollama_stream,
                            opencode_stream, github_models_stream)
    if llm is not None:
        self._llm: _LLMBackend = llm
    else:
        self._llm = self._build_backend(
            model=model, github_token=github_token, backend=backend,
            ollama_url=ollama_url, ollama_think=ollama_think,
            ollama_preserve_thinking=ollama_preserve_thinking, ollama_stream=ollama_stream,
            opencode_stream=opencode_stream, github_models_stream=github_models_stream,
            opencode_zen_api_key=opencode_zen_api_key, opencode_zen_base_url=opencode_zen_base_url,
            opencode_go_base_url=opencode_go_base_url, nvidia_nim_api_key=nvidia_nim_api_key,
            nvidia_nim_base_url=nvidia_nim_base_url, dashscope_api_key=dashscope_api_key,
            dashscope_url=dashscope_url, dashscope_think=dashscope_think,
            dashscope_preserve_thinking=dashscope_preserve_thinking, dashscope_stream=dashscope_stream,
            retry_delay=retry_delay, max_api_retries=max_api_retries, inter_call_delay=inter_call_delay,
        )
    self._backend: str = self._detect_backend_name()
    self._api_model: str = self._llm.model
    self.model = self._llm.model

def _init_retry_settings(self, retry_delay: int, max_api_retries: int, inter_call_delay: int) -> None:
    """Store retry/delay configuration on the instance."""
    self._retry_delay = retry_delay
    self._max_api_retries = max_api_retries
    self._inter_call_delay = inter_call_delay

def _init_stream_flags(self, ollama_think: bool, ollama_preserve_thinking: bool,
                       ollama_stream: bool, opencode_stream: bool,
                       github_models_stream: bool) -> None:
    """Store streaming/thinking flags on the instance."""
    self._ollama_think = ollama_think
    self._ollama_preserve_thinking = ollama_preserve_thinking
    self._ollama_stream = ollama_stream
    self._opencode_stream = opencode_stream
    self._github_models_stream = github_models_stream
```

- [ ] **Step 3: Refactor `truncate_files` (lines 555–602, 43 body lines)**

Extract the priority/scoring logic and the truncation loop:

```python
@staticmethod
def truncate_files(
    files: dict[str, str],
    max_chars: int = 80_000,
) -> dict[str, str]:
    """Truncate files to fit within max_chars, prioritising source over config files."""
    if sum(len(v) for v in files.values()) <= max_chars:
        return files
    sorted_paths = _sort_files_by_priority(files)
    return _truncate_to_budget(files, sorted_paths, max_chars)

def _sort_files_by_priority(files: dict[str, str]) -> list[str]:
    """Return file paths sorted by priority: source > tests > config > other."""
    def priority(path: str) -> int:
        if path.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".kt", ".swift")):
            return 0
        if path.endswith((".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".md")):
            return 2
        if "test" in path.lower():
            return 1
        return 1
    return sorted(files.keys(), key=priority)

def _truncate_to_budget(
    files: dict[str, str], sorted_paths: list[str], max_chars: int
) -> dict[str, str]:
    """Keep files in priority order until budget is exhausted."""
    result: dict[str, str] = {}
    remaining = max_chars
    for path in sorted_paths:
        content = files[path]
        if len(content) <= remaining:
            result[path] = content
            remaining -= len(content)
        elif remaining > 200:
            result[path] = content[:remaining] + f"\n... (truncated, {len(content)} chars total)"
            remaining = 0
        if remaining == 0:
            break
    return result
```

Note: `_sort_files_by_priority` and `_truncate_to_budget` are module-level functions (not methods) since they don't use `self`.

- [ ] **Step 4: Refactor `call` (lines 465–502, 37 body lines)**

Extract the message-building logic:

```python
def call(self, user_message: str, context: Optional[str] = None) -> str:
    """Send a message to the LLM and return the response."""
    full_message = f"{context}\n\n{user_message}" if context else user_message
    if self._backend in ("anthropic",) or self._is_anthropic_zen_go_backend():
        return self._call_anthropic(full_message)
    if self._backend == "opencode":
        return self._call_opencode(full_message)
    messages = self._build_messages(full_message)
    from llm_pool import get_pool
    with get_pool().acquire(self._backend):
        reply = self._llm.call(messages)
    self._record_exchange(full_message, reply)
    return reply

def _is_anthropic_zen_go_backend(self) -> bool:
    """Return True if the current backend uses an Anthropic client under the hood."""
    return (
        self._backend in ("opencode_zen", "opencode_go")
        and getattr(self._llm, "_anthropic_client", None) is not None
    )

def _build_messages(self, full_message: str) -> list[dict]:
    """Assemble the full messages list with system prompt + history + user turn."""
    messages: list[dict] = []
    if self.system_prompt:
        messages.append({"role": "system", "content": self.system_prompt})
    messages.extend(self._history)
    messages.append({"role": "user", "content": full_message})
    return messages
```

- [ ] **Step 5: Refactor `call_with_tools` (lines 504–550, 40 body lines)**

```python
def call_with_tools(
    self, user_message: str, tools: "ToolRegistry",
    context: Optional[str] = None, max_turns: int = 8,
) -> str:
    """Send a message to the LLM, executing tool calls until a final answer."""
    self._assert_tools_supported()
    full_message = f"{context}\n\n{user_message}" if context else user_message
    messages = self._build_messages(full_message)
    from llm_pool import get_pool
    with get_pool().acquire(self._backend):
        reply = self._llm.call_with_tools(messages, tools, max_turns)
    self._record_exchange(full_message, reply)
    return reply

def _assert_tools_supported(self) -> None:
    """Raise NotImplementedError if the current backend does not support tool calling."""
    if self._llm.supports_tools():
        return
    suffix = ""
    if self._backend == "opencode_go":
        suffix = " (MiniMax models use Anthropic endpoint)"
    elif self._backend == "opencode_zen":
        suffix = " (Claude models)"
    raise NotImplementedError(
        f"call_with_tools is not supported for the '{self._backend}' backend{suffix}. "
        "Use the 'github_models', 'ollama', 'opencode_zen' (non-Claude), "
        "or 'opencode_go' (non-MiniMax) backend for tool-calling."
    )
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```
Expected: same count as baseline, no failures.

- [ ] **Step 7: Verify base_agent violations cleared**

```bash
python -c "
import ast, pathlib
src = pathlib.Path('agents/base_agent.py').read_text()
tree = ast.parse(src)
violations = [n.name for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.end_lineno - n.body[0].lineno + 1 > 30]
print('Violations:', violations or 'NONE')
"
```
Expected: `Violations: NONE`

- [ ] **Step 8: Commit**

```bash
git add agents/base_agent.py
git commit -m "refactor(base_agent): split 5 functions to ≤30 lines

_build_backend (107→12 lines) → _resolve_backend_flags, _instantiate_backend,
  _try_opencode_backends, _try_cloud_backends, _try_local_backends
__init__ (46→30 lines) → _init_retry_settings, _init_stream_flags
truncate_files (43→10 lines) → _sort_files_by_priority, _truncate_to_budget
call (37→14 lines) → _build_messages, _is_anthropic_zen_go_backend
call_with_tools (40→12 lines) → _assert_tools_supported"
```

---

### Task 3: Refactor `agents/discussion_agent.py`

Four violations: `_call_participant` (84 lines, 297–387), `run` (65 lines, 574–646), `from_yaml` (63 lines, 94–157), `_select_participants` (56 lines, 431–487).

**Files:**
- Modify: `agents/discussion_agent.py`

- [ ] **Step 1: Understand the structure**

```bash
grep -n "def " agents/discussion_agent.py
```

- [ ] **Step 2: Refactor each violating method**

Apply the methodology: identify distinct responsibilities, extract private helpers. For each function:

- `_call_participant` (84 lines): handles homework round AND main discussion rounds AND mentions AND response recording. Extract: `_run_homework_if_needed(participant, context)` and `_build_participant_prompt(participant, mentions, history)` and `_record_participant_turn(role, response)`.
- `from_yaml` (63 lines): loads YAML, validates keys, resolves persona files, builds Participant list. Extract: `_load_yaml_config(path)`, `_resolve_personas(config, base_dir)`, `_build_participants(config)`.
- `_select_participants` (56 lines): filters by mention, applies max_participants cap, applies round-robin. Extract: `_filter_mentioned(participants, mentions)`, `_apply_participant_cap(participants, limit)`.
- `run` (65 lines): orchestrates phases. Extract: `_run_homework_phase(...)`, `_run_round_phase(...)`, `_build_output(...)`.

Each helper must be ≤30 lines.

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 4: Verify violations cleared**

```bash
python -c "
import ast, pathlib
src = pathlib.Path('agents/discussion_agent.py').read_text()
tree = ast.parse(src)
violations = [(n.name, n.end_lineno - n.body[0].lineno + 1) for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.end_lineno - n.body[0].lineno + 1 > 30]
print('Violations:', violations or 'NONE')
"
```

- [ ] **Step 5: Commit**

```bash
git add agents/discussion_agent.py
git commit -m "refactor(discussion_agent): split 4 functions to ≤30 lines"
```

---

### Task 4: Refactor `agents/conflict_resolver.py` and `agents/deploy_backends.py`

**conflict_resolver.py:** `_resolve` (77 lines, 87–171).
**deploy_backends.py:** `run` (76 lines), `_wait_for_ssh` (48), `_provision_vm` (40), `_run_via_compose` (33).

**Files:**
- Modify: `agents/conflict_resolver.py`
- Modify: `agents/deploy_backends.py`

- [ ] **Step 1: Refactor `conflict_resolver._resolve`**

`_resolve` builds the prompt, calls LLM, parses output, applies patches. Extract:
- `_build_conflict_prompt(file_path, conflict_blocks, design)` — builds the prompt string (≤30 lines)
- `_parse_resolved_content(response, file_path)` — extracts the resolved file content (≤15 lines)
- `_resolve` becomes: build prompt → call LLM → parse result (≤12 lines)

- [ ] **Step 2: Refactor `deploy_backends`**

- `run` (76 lines): orchestrates provision → wait → compose → verify. Extract: `_prepare_vm_environment(...)`, `_deploy_application(...)`, `_verify_deployment(...)`.
- `_wait_for_ssh` (48 lines): retry loop + connection test. Extract: `_attempt_ssh_connection(host, key_file)`.
- `_provision_vm` (40 lines): calls provider API + waits for VM ready. Extract: `_poll_vm_ready(vm_id, ...)`.
- `_run_via_compose` (33 lines): SCP + SSH execute. Extract: `_scp_compose_file(...)`.

- [ ] **Step 3: Run tests and verify**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
python -c "
import ast, pathlib
for f in ['agents/conflict_resolver.py', 'agents/deploy_backends.py']:
    src = pathlib.Path(f).read_text()
    tree = ast.parse(src)
    v = [(n.name, n.end_lineno - n.body[0].lineno + 1) for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.end_lineno - n.body[0].lineno + 1 > 30]
    print(f, '→', v or 'NONE')
"
```

- [ ] **Step 4: Commit**

```bash
git add agents/conflict_resolver.py agents/deploy_backends.py
git commit -m "refactor(conflict_resolver, deploy_backends): split functions to ≤30 lines"
```

---

### Task 5: Refactor `agents/engineer.py`, `agents/qa_engineer.py`, `agents/senior_engineer.py`

**engineer.py:** `run_module` (68), `run_with_github` (55), `run_all_modules` (39), `fix_failures` (38), `_parse_files` (33).
**qa_engineer.py:** `run` (70), `run_with_github` (52), `_parse_test_files` (39).
**senior_engineer.py:** `run_module` (56).

**Files:**
- Modify: `agents/engineer.py`
- Modify: `agents/qa_engineer.py`
- Modify: `agents/senior_engineer.py`

- [ ] **Step 1: Refactor `engineer.py`**

- `run_module` (68 lines): builds test_section, builds framework_section, builds prompt, calls LLM, parses files. Extract: `_build_test_section(test_files)`, `_build_module_prompt(module, design, project_name, framework_section, test_section, scaffold_hint)`. `run_module` becomes coordinator + tool-registry dispatch (~20 lines).
- `run_with_github` (55 lines): run_all_modules + branch create + file commits + PR open. Extract: `_commit_files_to_branch(github_client, files, branch_name, project_name)`, `_open_implementation_pr(github_client, project_name, modules, branch_name, issue_number)`. `run_with_github` becomes coordinator (~15 lines).
- `run_all_modules` (39 lines): already borderline — extract `_submit_module_futures(executor, modules, ...)` to make it ≤30 lines.
- `fix_failures` (38 lines): extract `_build_fix_prompt(failure_output, all_files, design, project_name, framework_section)`.
- `_parse_files` (33 lines): extract `_extract_file_blocks(lines)` inner loop. Move fallback logic out.

- [ ] **Step 2: Refactor `qa_engineer.py`**

- `run` (70 lines): reads test context, builds prompt, calls LLM, parses files. Extract: `_build_qa_prompt(design, module, ...)`, `_collect_test_context(all_files, design)`.
- `run_with_github` (52 lines): same pattern as engineer's `run_with_github`. Extract: `_commit_test_files(...)`, `_open_qa_pr(...)`.
- `_parse_test_files` (39 lines): same pattern as `_parse_files`. Extract inner loop.

- [ ] **Step 3: Refactor `senior_engineer.run_module` (56 lines)**

`SeniorEngineerAgent` inherits from `EngineerAgent`. `run_module` adds context injection around the parent call. Extract: `_build_senior_context(all_files)`, `_trim_context_to_budget(context, budget)`.

- [ ] **Step 4: Run tests and verify**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
python -c "
import ast, pathlib
for f in ['agents/engineer.py', 'agents/qa_engineer.py', 'agents/senior_engineer.py']:
    src = pathlib.Path(f).read_text()
    tree = ast.parse(src)
    v = [(n.name, n.end_lineno - n.body[0].lineno + 1) for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.end_lineno - n.body[0].lineno + 1 > 30]
    print(f, '→', v or 'NONE')
"
```

- [ ] **Step 5: Commit**

```bash
git add agents/engineer.py agents/qa_engineer.py agents/senior_engineer.py
git commit -m "refactor(engineer, qa_engineer, senior_engineer): split functions to ≤30 lines"
```

---

### Task 6: Refactor `agents/token_ledger.py`, `agents/pr_proposal.py`, `agents/pr_analyst.py`, `agents/pr_creative.py`

**token_ledger.py:** `flush_to_db` (66), `estimate_tokens` (49), `summary` (49).
**pr_proposal.py:** `_create_pr_with_retry` (62), `run` (47), `_construct_user_prompt` (39).
**pr_analyst.py:** `run` (44), `_parse_and_validate_json` (42), `_parse_brief` (36), `_construct_user_prompt` (35), `_retry_with_fallback_prompt` (33), `_validate_output_types` (32).
**pr_creative.py:** `_parse_and_validate_concepts` (45).

**Files:**
- Modify: `agents/token_ledger.py`
- Modify: `agents/pr_proposal.py`
- Modify: `agents/pr_analyst.py`
- Modify: `agents/pr_creative.py`

- [ ] **Step 1: Refactor `token_ledger.py`**

- `flush_to_db` (66 lines): opens DB, builds INSERT, executes batch, handles errors. Extract: `_build_insert_rows(records)`, `_execute_flush(conn, rows)`.
- `estimate_tokens` (49 lines): multiple if/elif model branches. Extract per-family helpers: `_estimate_gpt_tokens(text)`, `_estimate_claude_tokens(text)`, `_estimate_default_tokens(text)`.
- `summary` (49 lines): iterates records, groups by model, formats table. Extract: `_group_by_model(records)`, `_format_summary_table(groups)`.

- [ ] **Step 2: Refactor `pr_proposal.py`**

- `_create_pr_with_retry` (62 lines): retry loop + PR body build + GitHub call. Extract: `_build_pr_body(brief, branch)`, `_attempt_pr_creation(github_client, title, body, branch)`.
- `run` (47 lines): prompt → LLM → parse. Extract: `_build_proposal_prompt(brief, design)`.
- `_construct_user_prompt` (39 lines): already a helper; extract inner formatting logic.

- [ ] **Step 3: Refactor `pr_analyst.py`**

All 6 violations are in this file. Most are already reasonably named private helpers. Where they exceed 30 lines, extract the inner logic. E.g.:
- `_parse_and_validate_json` (42 lines): extract `_strip_json_fences(text)` (5 lines) and `_parse_json_field(data, field)`.
- `_validate_output_types` (32 lines): extract `_check_field_type(value, expected_type, field_name)`.

- [ ] **Step 4: Refactor `pr_creative._parse_and_validate_concepts` (45 lines)**

Extract: `_extract_concepts_json(response)` and `_validate_concept_schema(data)`.

- [ ] **Step 5: Run tests and verify**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
python -c "
import ast, pathlib
for f in ['agents/token_ledger.py', 'agents/pr_proposal.py', 'agents/pr_analyst.py', 'agents/pr_creative.py']:
    src = pathlib.Path(f).read_text()
    tree = ast.parse(src)
    v = [(n.name, n.end_lineno - n.body[0].lineno + 1) for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.end_lineno - n.body[0].lineno + 1 > 30]
    print(f, '→', v or 'NONE')
"
```

- [ ] **Step 6: Commit**

```bash
git add agents/token_ledger.py agents/pr_proposal.py agents/pr_analyst.py agents/pr_creative.py
git commit -m "refactor(token_ledger, pr_proposal, pr_analyst, pr_creative): split functions to ≤30 lines"
```

---

### Task 7: Refactor remaining 8 agent files

Files and violations:
- `agents/bootstrap_patterns_agent.py`: `run` (59 lines, 36–95)
- `agents/architect.py`: `_parse_modules` (56 lines, 136–192), `run_revision` (33, 73–113)
- `agents/documentation_agent.py`: `run` (50, 83–139), `_build_file_context` (40, 39–81)
- `agents/news_editor.py`: `run` (45, 17–68)
- `agents/news_reviewer.py`: `run` (46, 107–158)
- `agents/news_writer.py`: `run` (38, 27–65)
- `agents/qa_planner.py`: `run` (43, 29–79)
- `agents/deployment_tester.py`: `run` (41, 38–79), `_run_via_compose` (32, 145–177)

**Files:**
- Modify all 8 files above.

- [ ] **Step 1: Refactor each file using the standard methodology**

For each file, read the violating function(s), identify 2–4 distinct concerns, extract private helpers with descriptive names. Each helper ≤30 lines.

Common patterns:
- `run` methods typically: build prompt → call LLM → parse response → return structured result. Extract: `_build_<role>_prompt(...)` and `_parse_<role>_response(response)`.
- `_parse_modules` in architect: extract `_split_module_blocks(text)` and `_parse_single_module(block)`.
- `_build_file_context` in documentation_agent: extract `_select_files_for_context(all_files, budget)` and `_format_file_context(selected)`.

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 3: Verify all 8 files clear**

```bash
python -c "
import ast, pathlib
files = [
    'agents/bootstrap_patterns_agent.py', 'agents/architect.py',
    'agents/documentation_agent.py', 'agents/news_editor.py',
    'agents/news_reviewer.py', 'agents/news_writer.py',
    'agents/qa_planner.py', 'agents/deployment_tester.py',
]
for f in files:
    src = pathlib.Path(f).read_text()
    tree = ast.parse(src)
    v = [(n.name, n.end_lineno - n.body[0].lineno + 1) for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.end_lineno - n.body[0].lineno + 1 > 30]
    print(f.split('/')[-1], '→', v or 'NONE')
"
```

- [ ] **Step 4: Commit**

```bash
git add agents/bootstrap_patterns_agent.py agents/architect.py agents/documentation_agent.py \
        agents/news_editor.py agents/news_reviewer.py agents/news_writer.py \
        agents/qa_planner.py agents/deployment_tester.py
git commit -m "refactor(agents): split run/parse functions to ≤30 lines in 8 agents"
```

---

### Task 8: Refactor remaining small violators

Files and violations:
- `agents/memory_bank_updater.py`: `update` (34 lines, 35–73)
- `agents/product_manager.py`: `run` (38, 20–58), `run_revision` (37, 82–126)
- `agents/architect_reviewer.py`: `run` (34, 22–56)
- `agents/code_reviewer.py`: `run` (35, 32–67)
- `agents/pm_reviewer.py`: `run` (34, 22–56)

**Files:**
- Modify the 5 files above.

- [ ] **Step 1: Refactor each file**

All violations are `run` or `run_revision` methods. Pattern: extract `_build_<role>_prompt(...)` for prompt construction (typically 10–20 lines) and `_parse_<role>_result(response)` for parsing (5–15 lines).

- [ ] **Step 2: Run tests and verify all clear**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -5
python -c "
import ast, pathlib
files = ['agents/memory_bank_updater.py', 'agents/product_manager.py',
         'agents/architect_reviewer.py', 'agents/code_reviewer.py', 'agents/pm_reviewer.py']
for f in files:
    src = pathlib.Path(f).read_text()
    tree = ast.parse(src)
    v = [(n.name, n.end_lineno - n.body[0].lineno + 1) for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.end_lineno - n.body[0].lineno + 1 > 30]
    print(f.split('/')[-1], '→', v or 'NONE')
"
```

- [ ] **Step 3: Commit**

```bash
git add agents/memory_bank_updater.py agents/product_manager.py \
        agents/architect_reviewer.py agents/code_reviewer.py agents/pm_reviewer.py
git commit -m "refactor(agents): split run functions to ≤30 lines in 5 agents"
```

---

### Task 9: Final verification and PR-A

- [ ] **Step 1: Run fn_map to confirm zero violations in agents/**

```bash
python tools/fn_map.py --no-html 2>&1 | grep -E "violation|Violation"
```
Expected: output shows `0 violations` in agents/.

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: same count as baseline (Task 1 Step 1), all passing.

- [ ] **Step 3: Push and open PR-A**

```bash
git push -u origin feat/agent-30-line-refactor
gh pr create \
  --title "refactor(agents): apply ≤30-line function rule to all 24 agent files" \
  --body "$(cat <<'EOF'
## What

Applies the ≤30-line function body rule uniformly across all agent Python files — the same rule already applied to \`orchestrator.py\` in PR #88.

## Scope

24 agent files refactored. All functions now have ≤30-line bodies. \`tools/fn_map.py\` reports zero violations in \`agents/\`.

## Method

- Identified 2–4 distinct concerns in each large function
- Extracted private helpers (\`_build_xyz\`, \`_parse_xyz\`, \`_validate_xyz\`)
- Public API unchanged — no callers broken
- All 1780+ tests pass

## Files changed

\`base_agent.py\`, \`discussion_agent.py\`, \`conflict_resolver.py\`, \`deploy_backends.py\`, \`engineer.py\`, \`qa_engineer.py\`, \`senior_engineer.py\`, \`token_ledger.py\`, \`pr_proposal.py\`, \`pr_analyst.py\`, \`pr_creative.py\`, \`bootstrap_patterns_agent.py\`, \`architect.py\`, \`documentation_agent.py\`, \`news_editor.py\`, \`news_reviewer.py\`, \`news_writer.py\`, \`qa_planner.py\`, \`memory_bank_updater.py\`, \`product_manager.py\`, \`architect_reviewer.py\`, \`code_reviewer.py\`, \`pm_reviewer.py\`, \`deployment_tester.py\`
EOF
)" \
  --base master
```

---

## PR-B: Inject `<coding_standards>` into Agent Role Prompts

### Task 10: Branch setup

- [ ] **Step 1: Create PR-B branch**

```bash
git checkout master
git pull
git checkout -b feat/agent-coding-standards-prompts
```

---

### Task 11: Add `<coding_standards>` block to engineer and senior_engineer prompts

**Files:**
- Modify: `roles/engineer.md`
- Modify: `roles/senior_engineer.md`

- [ ] **Step 1: Append to `roles/engineer.md`**

Add the following block at the very end of the file (after any existing `## Anti-patterns` section):

```markdown
## Coding Standards

<coding_standards>
FUNCTION SIZE RULE:
- Every function body must be ≤30 lines.
- If a function needs more than 30 lines, it is doing too much.
  Break it into named helpers with clear single responsibilities.
  Name helpers descriptively: _parse_xyz, _build_xyz, _validate_xyz.
- When you read existing code that violates this rule, include a
  "Violations flagged:" note in your output listing the offending
  function names and their line counts. Do NOT refactor them unless
  explicitly instructed to do so.

FUNCTION MAP:
- At the end of every module you write or significantly modify,
  append a `# --- fn_map ---` comment block listing every function
  in the module and the functions it calls.
  Format (one function per line):
    # parent_function -> [child1, child2]
  If a function calls no others in the module, write:
    # leaf_function -> []
  This block is used by automated tooling to verify function hierarchy.
</coding_standards>
```

- [ ] **Step 2: Apply the same block to `roles/senior_engineer.md`**

Same block, appended at end of file.

- [ ] **Step 3: Verify the block is present in both files**

```bash
grep -c "coding_standards" roles/engineer.md roles/senior_engineer.md
```
Expected: `roles/engineer.md:2` and `roles/senior_engineer.md:2` (opening + closing tags).

- [ ] **Step 4: Commit**

```bash
git add roles/engineer.md roles/senior_engineer.md
git commit -m "feat(roles): add coding_standards block to engineer and senior_engineer prompts"
```

---

### Task 12: Add `<coding_standards>` to qa_engineer, architect, and conflict_resolver prompts

**Files:**
- Modify: `roles/qa_engineer.md`
- Modify: `roles/architect.md`
- Modify: `roles/conflict_resolver.md`

- [ ] **Step 1: Append the coding_standards block to each file**

Add exactly the same `## Coding Standards` section (same content as Task 11 Step 1) to the end of each of the three files.

- [ ] **Step 2: Verify**

```bash
grep -c "coding_standards" roles/qa_engineer.md roles/architect.md roles/conflict_resolver.md
```
Expected: `2` for each.

- [ ] **Step 3: Commit**

```bash
git add roles/qa_engineer.md roles/architect.md roles/conflict_resolver.md
git commit -m "feat(roles): add coding_standards block to qa_engineer, architect, conflict_resolver"
```

---

### Task 13: Add `<coding_standards>` to code_reviewer and documentation_agent prompts

**Files:**
- Modify: `roles/code_reviewer.md`
- Modify: `roles/documentation_agent.md`

- [ ] **Step 1: Append the coding_standards block to both files**

Same `## Coding Standards` section as Tasks 11–12.

- [ ] **Step 2: Verify all 7 files**

```bash
grep -l "coding_standards" roles/engineer.md roles/senior_engineer.md roles/qa_engineer.md \
  roles/architect.md roles/conflict_resolver.md roles/code_reviewer.md roles/documentation_agent.md
```
Expected: all 7 filenames listed.

- [ ] **Step 3: Commit and push PR-B**

```bash
git add roles/code_reviewer.md roles/documentation_agent.md
git commit -m "feat(roles): add coding_standards block to code_reviewer and documentation_agent"

git push -u origin feat/agent-coding-standards-prompts
gh pr create \
  --title "feat(roles): inject coding_standards block into 7 agent role prompts" \
  --body "Adds a <coding_standards> section to the system prompts of all code-generating agents:
engineer, senior_engineer, qa_engineer, architect, conflict_resolver, code_reviewer, documentation_agent.

The block enforces:
- ≤30-line function bodies
- fn_map comment block at end of every module written/modified
- Flag (but don't auto-fix) violations in existing code read

Part B of the agent-30-line-rule design spec." \
  --base master
```

---

## PR-C: Post-generation Validator

> **Prerequisite:** PR-B must be merged before this PR's changes take effect. PR-C can be implemented in parallel but should only merge after PR-B.

### Task 14: Add `validate_function_sizes()` to `tools/fn_map.py`

**Files:**
- Modify: `tools/fn_map.py`
- Create: `tests/test_validate_function_sizes.py`

- [ ] **Step 1: Write failing tests first**

Create `tests/test_validate_function_sizes.py`:

```python
"""Tests for tools.fn_map.validate_function_sizes."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.fn_map import validate_function_sizes


def _write_py(tmp_path: Path, filename: str, src: str) -> Path:
    p = tmp_path / filename
    p.write_text(textwrap.dedent(src))
    return p


def test_returns_empty_for_compliant_file(tmp_path):
    f = _write_py(tmp_path, "ok.py", """\
        def small():
            x = 1
            return x
    """)
    assert validate_function_sizes([f]) == []


def test_detects_oversized_function(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    src = f"def big_fn():\n{body}\n    return x0\n"
    f = _write_py(tmp_path, "big.py", src)
    violations = validate_function_sizes([f])
    assert len(violations) == 1
    assert "big_fn" in violations[0]
    assert "36" in violations[0] or "35" in violations[0]


def test_violation_string_format(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    src = f"def bad_fn():\n{body}\n    return x0\n"
    f = _write_py(tmp_path, "module.py", src)
    violations = validate_function_sizes([f])
    assert violations[0].startswith("module.py::bad_fn")


def test_custom_limit(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(20))
    src = f"def medium_fn():\n{body}\n    return x0\n"
    f = _write_py(tmp_path, "m.py", src)
    assert validate_function_sizes([f], limit=30) == []
    assert validate_function_sizes([f], limit=15) != []


def test_syntax_error_returns_empty(tmp_path):
    f = _write_py(tmp_path, "bad_syntax.py", "def broken(\n")
    assert validate_function_sizes([f]) == []


def test_multiple_files(tmp_path):
    ok = _write_py(tmp_path, "ok.py", "def fine():\n    return 1\n")
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    bad = _write_py(tmp_path, "bad.py", f"def large():\n{body}\n    return x0\n")
    violations = validate_function_sizes([ok, bad])
    assert len(violations) == 1
    assert "bad.py" in violations[0]
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_validate_function_sizes.py -v 2>&1 | tail -15
```
Expected: `ImportError` or `AttributeError` — `validate_function_sizes` not yet defined.

- [ ] **Step 3: Implement `validate_function_sizes` in `tools/fn_map.py`**

Add immediately after the `detect_violations` function (line ~151):

```python
def validate_function_sizes(
    files: list[Path],
    limit: int = 30,
) -> list[str]:
    """Return violation strings for functions exceeding limit lines.

    Each string has the format: "filename.py::function_name (N lines)".
    Returns an empty list if all functions are within the limit.
    Silently skips files with syntax errors.
    """
    from pathlib import Path as _Path
    root = _Path(".")
    paths = [_Path(f) if not isinstance(f, _Path) else f for f in files]
    funcs = collect_functions(paths, root)
    violations = detect_violations(funcs, limit)
    return [f"{v.file}::{v.name} ({v.line_count} lines)" for v in violations]
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
python -m pytest tests/test_validate_function_sizes.py -v 2>&1 | tail -15
```
Expected: all 6 tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add tools/fn_map.py tests/test_validate_function_sizes.py
git commit -m "feat(fn_map): add validate_function_sizes() helper"
```

---

### Task 15: Add `_after_write()` hook to `agents/base_agent.py`

This hook is called whenever an agent writes code files to disk. It validates the written files and, if violations are found, raises a structured exception that the caller can catch and use to prompt the agent to revise.

**Files:**
- Modify: `agents/base_agent.py`
- Modify: `tests/test_base_agent.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_base_agent_extended.py`:

```python
# --- _after_write tests ---

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
```

- [ ] **Step 2: Run failing tests**

```bash
python -m pytest tests/test_base_agent_extended.py -k "after_write" -v 2>&1 | tail -10
```
Expected: `AttributeError: 'BaseAgent' object has no attribute '_after_write'`

- [ ] **Step 3: Implement `_after_write` in `agents/base_agent.py`**

Add after the `_build_messages` helper (near line ~505):

```python
def _after_write(self, files: list) -> list[str]:
    """Validate written files for function size violations.

    Call this after writing code files to disk. Returns a list of
    violation strings (empty if all functions are within the 30-line limit).
    Used by the post-generation validation loop.
    """
    from pathlib import Path
    from tools.fn_map import validate_function_sizes
    py_files = [Path(f) for f in files if str(f).endswith(".py")]
    if not py_files:
        return []
    try:
        return validate_function_sizes(py_files)
    except Exception as exc:  # noqa: BLE001 — validation must never break the pipeline
        _log.warning("_after_write: validation error: %s", exc)
        return []
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_base_agent_extended.py -k "after_write" -v 2>&1 | tail -10
```
Expected: both tests `PASSED`.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: same count as baseline, all passing.

- [ ] **Step 6: Commit**

```bash
git add agents/base_agent.py tests/test_base_agent_extended.py
git commit -m "feat(base_agent): add _after_write() hook for post-generation size validation"
```

---

### Task 16: Integration test and PR-C

**Files:**
- Create: `tests/test_after_write_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_after_write_integration.py`:

```python
"""Integration test: _after_write violations are injected into agent feedback."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.base_agent import BaseAgent


def _make_agent(tmp_path: Path) -> BaseAgent:
    llm = MagicMock()
    llm.model = "gpt-4.1"
    llm.supports_tools.return_value = False
    return BaseAgent(model="gpt-4.1", llm=llm)


def test_after_write_returns_violations_for_big_function(tmp_path):
    """_after_write returns non-empty list when a written file has a >30-line function."""
    body = "\n".join(f"    var_{i} = {i}" for i in range(35))
    code = f"def process():\n{body}\n    return var_0\n"
    f = tmp_path / "service.py"
    f.write_text(code)

    agent = _make_agent(tmp_path)
    violations = agent._after_write([f])

    assert len(violations) == 1
    assert "process" in violations[0]
    assert "service.py" in violations[0]


def test_after_write_returns_empty_for_compliant_file(tmp_path):
    """_after_write returns empty list when all functions are ≤30 lines."""
    code = textwrap.dedent("""\
        def helper_a():
            return 1

        def helper_b():
            return 2
    """)
    f = tmp_path / "clean.py"
    f.write_text(code)

    agent = _make_agent(tmp_path)
    assert agent._after_write([f]) == []


def test_after_write_ignores_non_python_files(tmp_path):
    """_after_write skips non-.py files silently."""
    f = tmp_path / "config.yaml"
    f.write_text("key: value\n")
    agent = _make_agent(tmp_path)
    assert agent._after_write([f]) == []
```

- [ ] **Step 2: Run integration tests**

```bash
python -m pytest tests/test_after_write_integration.py -v 2>&1 | tail -15
```
Expected: all 3 tests `PASSED`.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -5
```

- [ ] **Step 4: Create branch, commit, push, open PR-C**

```bash
git checkout master
git pull
git checkout -b feat/agent-post-generation-validator

# Cherry-pick or re-apply the fn_map and base_agent changes
# (or if working directly: git add all changed files)
git add tools/fn_map.py tests/test_validate_function_sizes.py \
        agents/base_agent.py tests/test_base_agent.py \
        tests/test_after_write_integration.py
git commit -m "feat: add post-generation function size validator

- tools/fn_map.py: add validate_function_sizes(files, limit=30) -> list[str]
- agents/base_agent.py: add _after_write(files) hook (calls validate_function_sizes)
- tests: full unit + integration coverage for both"

git push -u origin feat/agent-post-generation-validator
gh pr create \
  --title "feat: add post-generation function size validator" \
  --body "Part C of the agent-30-line-rule design spec.

## Changes

**\`tools/fn_map.py\`:** Adds \`validate_function_sizes(files, limit=30) -> list[str]\`  
Returns violation strings (\`path.py::fn_name (N lines)\`) for any function exceeding the limit. Reuses existing \`collect_functions\` + \`detect_violations\`.

**\`agents/base_agent.py\`:** Adds \`_after_write(files) -> list[str]\`  
Calls \`validate_function_sizes\` on any \`.py\` files written. Returns violations (empty list = all clean). Never raises — validation errors are logged as warnings so the pipeline continues.

## Usage

After an agent writes code files, call \`_after_write(written_files)\`. If the result is non-empty, inject the violations into the agent's next message:
\`\`\`python
violations = self._after_write(written_files)
if violations:
    feedback = 'The following functions exceed 30 lines:\\n' + '\\n'.join(violations)
    revised = self.call(feedback + '\\nPlease refactor them.')
\`\`\`

## Tests

- 6 unit tests for \`validate_function_sizes\`
- 2 unit tests for \`_after_write\`
- 3 integration tests

All 1780+ existing tests still pass." \
  --base master
```

---

## Completion Checklist

- [ ] PR-A merged: 24 agent files refactored, zero fn_map violations in `agents/`
- [ ] PR-B merged: 7 role prompts have `<coding_standards>` block
- [ ] PR-C merged (after PR-B): `validate_function_sizes` in fn_map, `_after_write` in base_agent, all tests pass
