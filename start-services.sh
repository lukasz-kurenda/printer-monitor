#!/bin/sh
# ============================================================
# Auto-start uslug printer-monitor (entrypoint kontenera).
# Wymaga: CAP_NET_ADMIN (aliasy IP symulatora), obraz z deps.
#
# Uruchamia: aliasy IP -> flota testowa (jesli pusta) ->
#            agent SNMP + web mock + gunicorn (dashboard).
# Kontener: --restart unless-stopped -> uslugi wracaja po
#           restarcie serwera/WSL/dockera automatycznie.
# ============================================================
set -e

cd /workspace || exit 1

# 1. Aliasy IP dla symulowanych drukarek (idempotentne)
if [ -f /workspace/simulator/ip-aliases.sh ]; then
    sh /workspace/simulator/ip-aliases.sh || true
fi

# 2. Flota testowa: regeneruj printers.csv, jesli pusty
if [ ! -s /workspace/printers.csv ]; then
    python simulator/rotate.py write-csv >/dev/null 2>&1 || true
fi

# 3. Uslugi (w tle, logi w /tmp)
nohup python -B simulator/snmp_agent.py > /tmp/snmp.log 2>&1 &
nohup python -B simulator/web_mock.py > /tmp/web.log 2>&1 &

# 3b. Dashboard - dwie instancje:
#   :5001 lokalna (auto-login, publikacja TYLKO 127.0.0.1)
#   :5002 VLAN dla administratorow (tryb tokenowy, config [WWW] auto_login=false)
DASH_AUTO_LOGIN=true nohup gunicorn -w 1 --bind 0.0.0.0:5001 dashboard:app > /tmp/gunicorn-local.log 2>&1 &
nohup gunicorn -w 1 --bind 0.0.0.0:5002 dashboard:app > /tmp/gunicorn-vlan.log 2>&1 &

# 4. Utrzymuj kontener przy zyciu
sleep infinity
