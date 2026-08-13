#!/bin/bash
# Cron: toner check + e-mail alerts.
# Relative paths - works regardless of the invocation directory.
#
# === SCHEDULE - EDIT HERE (default: every 2 hours) ===
# crontab -e   (host):
#   5 */2 * * * /path/to/check_toners.sh
# (i.e. 00:05, 02:05, 04:05, ... 22:05; dashboard page states the same interval)
# =======================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

PYTHON="${SCRIPT_DIR}/venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

echo "$(date): check_toners.sh run by cron" >> "${LOG_DIR}/printer-monitor.log"
cd "$SCRIPT_DIR"
"$PYTHON" main.py --check-toner --force-toner-email >> "${LOG_DIR}/cron.log" 2>&1
