#!/bin/bash
# Uruchamia main.py z przekazanymi argumentami (np. --check-toner --force-toner-email).
# Sciezki wzgledne - dziala niezaleznie od katalogu wywolania.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

PYTHON="${SCRIPT_DIR}/venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

cd "$SCRIPT_DIR"
"$PYTHON" main.py "$@" >> "${LOG_DIR}/cron.log" 2>&1
