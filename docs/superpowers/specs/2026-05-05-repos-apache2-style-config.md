# Design: Apache2-Style repos-available / repos-enabled Config Split

**Date:** 2026-05-05  
**Status:** Approved

## Problem

`repos.yaml` is a single monolithic file holding all watcher entries. As the number of watched repositories grows, the file becomes hard to manage. Adding or removing a repo requires editing the file by hand, and there is no quick way to enable or disable a watcher without modifying shared state.

## Goal

Adopt the Apache2 `sites-available` / `sites-enabled` pattern:

- Each watched repo lives in its own YAML file under `repos-available/`
- Enabled repos are symlinked into `repos-enabled/`
- `watcher.py repo enable/disable/list` manages the symlinks
- `repos.yaml` remains the root config (global settings) and retains full backward compatibility

---

## Directory Structure

```
repos-available/
  mcp-tfl.yaml          ← one watcher per file
  custom-cms.yaml
  mybooking.yaml
repos-enabled/
  mcp-tfl.yaml          → /absolute/path/to/repos-available/mcp-tfl.yaml  (absolute symlink)
  custom-cms.yaml       → /absolute/path/to/repos-available/custom-cms.yaml
repos.yaml              ← global settings + optional legacy watchers:
```

> **Note:** symlinks are created as **absolute** paths (using `avail.resolve()`). Absolute symlinks are more portable across `--config` paths — relative symlinks would break whenever the working directory differs from the project root.

`repos-available/` and `repos-enabled/` live alongside `repos.yaml` (i.e. the project root). Their paths are derived relative to the root config file so `--config /path/to/repos.yaml` still works.

---

## Individual Repo File Format

Each file contains a single watcher entry — flat, with no `watchers:` wrapper. An optional `settings:` block overrides the global settings for that watcher only.

```yaml
# repos-available/mcp-tfl.yaml
tracker_repo: wanleung/mcp-tfl
default_target: ~
feature_label:
  - feature-request
  - ai-build
  - ai-feature
bug_label:
  - bug
  - ai-fix
doc_label: documentation
enabled: true          # optional; watcher respects this flag as before

settings:              # optional per-watcher overrides
  model: gpt-4.1-mini
  num_engineers: 1
```

**Convention:** file name = repository slug with owner stripped and `/` replaced by `-` (e.g. `wanleung/mcp-tfl` → `mcp-tfl`).  
The `enable` command takes the file name stem as an explicit argument (e.g. `repo enable mcp-tfl`). By convention, the stem matches the repo name with owner stripped and `/` replaced by `-`.

---

## Config Loading Logic

Current flow in `watch()` and `main()`:

```
open(config_path) → yaml.safe_load → config["watchers"]
```

New flow (additive, backward-compatible):

```
open(config_path) → yaml.safe_load → global_settings, legacy_watchers
  + glob(repos-enabled/*.yaml) → [per-repo watcher dicts]
  → merged_watchers = legacy_watchers + per_repo_watchers
```

Per-watcher `settings:` overrides: when dispatching a watcher, its `settings:` block (if present) is deep-merged over the global settings. Global settings remain the default for all watchers that do not specify their own.

The glob directory is resolved as:

```python
repos_enabled = config_path.parent / "repos-enabled"
```

If `repos-enabled/` does not exist, the watcher silently skips the glob (fully backward compatible — existing `repos.yaml`-only setups work unchanged).

---

## CLI Sub-Commands

New `repo` sub-command added to `watcher.py`:

```
python watcher.py repo enable  <name>   create symlink repos-enabled/<name>.yaml → ../repos-available/<name>.yaml
python watcher.py repo disable <name>   remove symlink repos-enabled/<name>.yaml
python watcher.py repo list             show all files in repos-available/ with [enabled] / [disabled] status
```

`<name>` is the filename stem (without `.yaml`).

**`repo enable <name>`:**
- Errors clearly if `repos-available/<name>.yaml` does not exist
- Creates `repos-enabled/` directory if it does not exist
- Errors if already enabled

**`repo disable <name>`:**
- Errors if not currently enabled
- Only removes the symlink; never touches `repos-available/`

**`repo list`:**
- Lists all `.yaml` files in `repos-available/`
- Marks each `[enabled]` or `[disabled]` based on whether a symlink exists in `repos-enabled/`

---

## Backward Compatibility

| Scenario | Behaviour |
|---|---|
| `repos.yaml` with `watchers:` list, no `repos-enabled/` dir | Unchanged — works exactly as before |
| Mix of legacy `watchers:` in `repos.yaml` AND `repos-enabled/` entries | Both are merged; duplicates (same `tracker_repo`) emit a warning and the enabled-dir entry wins |
| `enabled: false` inside a symlinked file | Still respected — watcher skips it (consistent with existing `enabled:` flag semantics) |
| `--config /custom/path/repos.yaml` | `repos-available/` and `repos-enabled/` are resolved relative to that config's parent directory |

---

## Migration (Optional)

No forced migration. Existing `repos.yaml` continues to work as-is.

To migrate a watcher entry manually:
1. Copy the watcher dict from `repos.yaml` into a new `repos-available/<name>.yaml` file (remove `watchers:` wrapper)
2. Run `python watcher.py repo enable <name>`
3. Remove the entry from `repos.yaml`

A helper `python watcher.py repo migrate` command could automate this in future, but is out of scope for this spec.

---

## Error Handling

- `repo enable <name>`: file not found in `repos-available/` → clear error, list available names
- `repo enable <name>`: already enabled → error "already enabled; run 'repo disable' first"
- `repo disable <name>`: not enabled → error "not currently enabled"
- `repos-enabled/` contains a broken symlink (target deleted) → warning logged at startup, entry skipped

---

## Testing

- Unit tests for the new config loading logic (existing `watchers:` only, `repos-enabled/` only, mixed)
- Unit tests for each `repo` sub-command (enable, disable, list — happy path + error cases)
- Test that per-watcher `settings:` override global settings correctly
- Test broken symlink handling

---

## Out of Scope

- `python watcher.py repo migrate` (auto-split legacy `repos.yaml`)
- Watching `repos-enabled/` for inotify-based reload
- Remote/URL-based repo config files
