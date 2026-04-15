#!/usr/bin/env bash
# setup_cron.sh — install the hourly watcher cron job
#
# Usage:
#   chmod +x setup_cron.sh
#   ./setup_cron.sh
#
# To remove the cron job:
#   crontab -e   # delete the line containing 'watcher.py'

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv/bin/activate"
WATCHER="$SCRIPT_DIR/watcher.py"
LOG_DIR="$SCRIPT_DIR/logs/watcher"

mkdir -p "$LOG_DIR"

# The cron command
CRON_CMD="0 * * * * cd $SCRIPT_DIR && source $VENV && python $WATCHER >> $LOG_DIR/cron.log 2>&1"

# Add only if not already present
if crontab -l 2>/dev/null | grep -qF "ai-software-house.*watcher.py"; then
    echo "✅ Cron job already installed."
    crontab -l | grep "ai-software-house.*watcher.py"
else
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "✅ Cron job installed — runs every hour at :00"
    echo "   $CRON_CMD"
fi

echo ""
echo "Useful commands:"
echo "  View cron jobs:          crontab -l"
echo "  View today's log:        tail -f $LOG_DIR/cron.log"
echo "  Run manually now:        cd $SCRIPT_DIR && source venv/bin/activate && python watcher.py"
echo "  Dry run (no changes):    cd $SCRIPT_DIR && source venv/bin/activate && python watcher.py --dry-run"
echo "  Remove cron job:         crontab -e  (delete the watcher.py line)"
