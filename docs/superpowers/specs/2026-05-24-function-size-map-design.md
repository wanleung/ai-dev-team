# Function Size Report & Map — Design

**Date:** 2026-05-24  
**Status:** Approved  
**Scope:** `ai-software-house` core files only

---

## Goal

An advisory tool (`tools/fn_map.py`) that analyses core Python files for function size
violations and generates an interactive HTML function map showing module structure and
call relationships. Nothing is blocked — it produces a report for human review.

The tool itself is a working example of the discipline it enforces: every internal
function stays under 30 lines.

---

## Configuration: `fn_map.yaml`

Committed to the repo root. All fields have defaults so an empty file is valid.

```yaml
limit: 30           # function line limit (default: 30)

include:            # paths relative to repo root; directories are walked recursively
  - orchestrator.py
  - watcher.py
  - rss_watcher.py
  - intake_triage.py
  - intake_scoring.py
  - main.py
  - tracker_adapter.py
  - config_schema.py
  - agents/
  - tools/

exclude:            # prefixes/patterns to skip
  - workspace/
  - .venv/
  - venv/
  - tests/
  - .git/
  - __pycache__/

output:
  html: fn_map.html   # path for generated HTML; set to null to skip HTML
```

CLI flags can override individual config values:

```bash
python tools/fn_map.py                     # use fn_map.yaml in cwd
python tools/fn_map.py --config <path>     # use alternate config file
python tools/fn_map.py --limit 50          # override limit
python tools/fn_map.py --no-html           # terminal report only
```

---

## Data Model

```python
@dataclass
class FunctionInfo:
    name: str
    file: str        # path relative to repo root
    lineno: int      # first line number
    line_count: int  # total lines including body
    calls: set[str]  # function names called from this function's AST body
```

---

## Internal Structure

Every function in `fn_map.py` stays under 30 lines. Public API surface:

| Function | Purpose |
|---|---|
| `load_config(path)` | Parse `fn_map.yaml`, apply defaults |
| `resolve_paths(include, exclude)` | Expand dirs, filter excludes → `list[Path]` |
| `collect_functions(paths)` | Walk all paths → `list[FunctionInfo]` |
| `_parse_file(path)` | AST parse one file → `list[FunctionInfo]` |
| `_extract_calls(node)` | Walk `ast.Call` nodes → `set[str]` of called names |
| `detect_violations(funcs, limit)` | Filter `line_count > limit`, sort desc |
| `build_distribution(funcs, buckets)` | Bucket counts for histogram |
| `build_call_index(funcs)` | `name → FunctionInfo` for call resolution |
| `print_terminal_report(funcs, limit)` | Print violations table + distribution |
| `generate_html(funcs, limit, path)` | Write self-contained HTML map |
| `_render_module_group(file, funcs, limit)` | HTML for one file's card group |
| `_render_function_card(fn, limit)` | HTML for one function card |
| `main()` | Parse CLI args, load config, run analysis, call outputs |

---

## Terminal Output

```
Function Size Report  (limit: 30 lines)
─────────────────────────────────────────────────────────
 Lines  Function                       File
─────────────────────────────────────────────────────────
   325  __init__                       orchestrator.py:667
   315  run                            orchestrator.py:2876
   ...
─────────────────────────────────────────────────────────
871 violations  |  6546 compliant (88%)  |  7417 total

Distribution:
  ≤ 10 lines   ████████████████████████  3721  50%
  ≤ 20 lines   █████████████             1979  27%
  ≤ 30 lines   ██████                     846  11%
  ≤ 50 lines   ████                       581   8%
  ≤100 lines   ██                         250   3%
  > 100 lines  ·                           40  <1%

HTML map written → fn_map.html
```

Colour coding: red for > 50 lines, orange for 31–50, green for ≤ 30.

---

## HTML Function Map

A **self-contained static HTML file** — no server, no external dependencies.
All CSS and JavaScript is inlined.

### Layout

- **Left sidebar** — file list with per-file violation badge (red/orange/green)
- **Main area** — module boxes, one per file
  - Each box shows function cards, colour-coded by size:
    - Green border: ≤ limit lines
    - Orange border: limit+1 – 50 lines
    - Red border: > 50 lines
  - Each card shows: function name, line count, source line, number of outgoing calls
- **Detail panel** (appears on click) — shows the selected function's:
  - Calls list (functions it calls, with cross-links if in the analysis set)
  - Called-by list (functions that call it)

### Filters

Top bar has three filter buttons: **All** / **Violations only** / **>50 lines**.
Clicking a filter hides cards not matching the criteria.

### Call Resolution

- Static AST-based: walks `ast.Call` nodes inside each function body
- Resolves by name only — best-effort, no import tracing
- Cross-file calls are resolved when both sides are in the analysis set
- Unresolved calls are shown in the detail panel as plain text (not linked)

### What the HTML map does NOT do

- Does not draw arrows/edges as SVG lines between boxes (too dense at scale)
- Does not track history or trends
- Does not auto-refactor code

---

## File Layout

```
ai-software-house/
  tools/
    fn_map.py         # the script (new)
  fn_map.yaml         # config (new, committed)
  fn_map.html         # generated output (new, gitignored)
  .gitignore          # add fn_map.html entry
```

---

## Scope Limits

This design covers **advisory reporting only**. The following are explicitly out of scope:

- CI enforcement / pre-commit hooks
- Trend tracking over time
- Auto-refactoring suggestions
- Coverage of `workspace/` (AI-generated client code)
