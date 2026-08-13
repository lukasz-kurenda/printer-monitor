#!/bin/sh
# ============================================================
# Auto-start of printer-monitor services (container entrypoint).
# Requires: CAP_NET_ADMIN (simulator IP aliases), image with deps.
#
# Starts: IP aliases -> test fleet (if empty) ->
#         SNMP agent + web mock + gunicorn (dashboard).
# Container: --restart unless-stopped -> services come back
#            automatically after a server/WSL/docker restart.
# ============================================================
set -e

cd /workspace || exit 1

# 1. IP aliases for simulated printers (idempotent)
if [ -f /workspace/simulator/ip-aliases.sh ]; then
    sh /workspace/simulator/ip-aliases.sh || true
fi

# 2. Test fleet: regenerate printers.csv if empty
if [ ! -s /workspace/printers.csv ]; then
    python simulator/rotate.py write-csv >/dev/null 2>&1 || true
fi

# 3. Services (background, logs in /tmp)
nohup python -B simulator/snmp_agent.py > /tmp/snmp.log 2>&1 &
nohup python -B simulator/web_mock.py > /tmp/web.log 2>&1 &

# 3b. Dashboard - two instances:
#   :5001 local (auto-login, published ONLY on 127.0.0.1)
#   :5002 VLAN for administrators (token mode, config [WWW] auto_login=false)
DASH_AUTO_LOGIN=true nohup gunicorn -w 1 --bind 0.0.0.0:5001 dashboard:app > /tmp/gunicorn-local.log 2>&1 &
nohup gunicorn -w 1 --bind 0.0.0.0:5002 dashboard:app > /tmp/gunicorn-vlan.log 2>&1 &

# 4. Keep the container alive
sleep infinity
