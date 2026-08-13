#!/bin/bash
# Cron: sprawdzanie tonerow + alerty e-mail.
# Sciezki wzgledne - dziala niezaleznie od katalogu wywolania.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

PYTHON="${SCRIPT_DIR}/venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

echo "$(date): check_toners.sh uruchomiony przez cron" >> "${LOG_DIR}/printer-monitor.log"
cd "$SCRIPT_DIR"
"$PYTHON" main.py --check-toner --force-toner-email >> "${LOG_DIR}/cron.log" 2>&1
