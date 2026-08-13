#!/bin/bash
# Cron: counter report + e-mail send.
# Relative paths - works regardless of the invocation directory.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

PYTHON="${SCRIPT_DIR}/venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

cd "$SCRIPT_DIR"
"$PYTHON" main.py --report-counters --force-counters-email >> "${LOG_DIR}/cron.log" 2>&1
