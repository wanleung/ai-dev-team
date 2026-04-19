#!/usr/bin/env bash
# Wrapper for cron — sources environment before running watcher.py so that
# tools like 'opencode' (installed via npm) are on PATH.
set -euo pipefail

# Load user environment (PATH, API keys, etc.)
# shellcheck source=/dev/null
[ -f "$HOME/.bash_env" ] && source "$HOME/.bash_env"

# Ensure npm-global bin is on PATH (opencode CLI lives here)
export PATH="$HOME/.npm-global/bin:$PATH"

cd "$(dirname "$0")"
exec venv/bin/python watcher.py "$@"
