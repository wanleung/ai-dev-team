#!/usr/bin/env bash
# setup_cron.sh — install cron jobs for the ai-software-house watcher and press maintenance
#
# Usage:
#   chmod +x setup_cron.sh
#   ./setup_cron.sh
#
# To remove cron jobs:
#   crontab -e   # delete lines containing 'watcher.py' or 'press_maintenance.py'

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"
WATCHER="$SCRIPT_DIR/watcher.py"
MAINTENANCE="$SCRIPT_DIR/scripts/press_maintenance.py"
LOG_DIR="$SCRIPT_DIR/logs/watcher"
MAINT_LOG="$SCRIPT_DIR/logs/press_maintenance.log"

mkdir -p "$LOG_DIR"

# cron does not source ~/.bash_env, so we must pass GITHUB_TOKEN explicitly.
# Pull it from ~/.bash_env at install time and embed it in the cron line.
GITHUB_TOKEN_VAL="$(bash -c 'source ~/.bash_env 2>/dev/null; echo $GITHUB_TOKEN')"

# Use the venv python directly — 'source activate' is bash-specific and breaks in cron's /bin/sh
CRON_WATCHER="0 * * * * cd $SCRIPT_DIR && $VENV_PYTHON $WATCHER >> $LOG_DIR/cron.log 2>&1"
CRON_MAINT="*/15 * * * * cd $SCRIPT_DIR && GITHUB_TOKEN=$GITHUB_TOKEN_VAL $VENV_PYTHON $MAINTENANCE >> $MAINT_LOG 2>&1"

# ── Watcher (hourly) ─────────────────────────────────────────────────────────
if crontab -l 2>/dev/null | grep -qF "ai-software-house.*watcher.py"; then
    echo "✅ Watcher cron job already installed."
    crontab -l | grep "ai-software-house.*watcher.py"
else
    (crontab -l 2>/dev/null; echo "$CRON_WATCHER") | crontab -
    echo "✅ Watcher cron job installed — runs every hour at :00"
    echo "   $CRON_WATCHER"
fi

# ── Press maintenance (every 15 minutes) ─────────────────────────────────────
if crontab -l 2>/dev/null | grep -qF "press_maintenance.py"; then
    echo "✅ Press maintenance cron job already installed."
    crontab -l | grep "press_maintenance.py"
else
    (crontab -l 2>/dev/null; echo "$CRON_MAINT") | crontab -
    echo "✅ Press maintenance cron job installed — runs every 15 minutes"
    echo "   $CRON_MAINT"
fi

echo ""
echo "Useful commands:"
echo "  View cron jobs:           crontab -l"
echo "  View watcher log:         tail -f $LOG_DIR/cron.log"
echo "  View maintenance log:     tail -f $MAINT_LOG"
echo "  Run watcher now:          cd $SCRIPT_DIR && venv/bin/python watcher.py"
echo "  Run maintenance now:      cd $SCRIPT_DIR && venv/bin/python scripts/press_maintenance.py"
echo "  Dry run maintenance:      cd $SCRIPT_DIR && venv/bin/python scripts/press_maintenance.py --dry-run"
echo "  Run one job only:         ... press_maintenance.py --job merge|stuck-running|stuck-complete"
echo "  Remove cron jobs:         crontab -e  (delete lines with watcher.py / press_maintenance.py)"
