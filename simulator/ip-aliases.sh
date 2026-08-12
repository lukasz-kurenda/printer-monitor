#!/bin/sh
# Nadaje aliasy IP (z seed.json) na eth0 - wymaga CAP_NET_ADMIN.
# Uruchamiane przy starcie kontenera oraz recznie po `docker restart`.
set -e

SIM_DIR="$(cd "$(dirname "$0")" && pwd)"
SEED="$SIM_DIR/seed.json"

if [ ! -f "$SEED" ]; then
    echo "Brak seed.json w $SIM_DIR"
    exit 1
fi

for ip in $(python -c "
import json
print(' '.join(p['ip'] for p in json.load(open('$SEED'))['printers']))
"); do
    if ip addr show dev eth0 | grep -q "inet $ip/"; then
        echo "OK   $ip (juz jest)"
    elif ip addr add "$ip/16" dev eth0 2>/dev/null; then
        echo "ADD  $ip"
    else
        echo "FAIL $ip (brak CAP_NET_ADMIN?)"
    fi
done
