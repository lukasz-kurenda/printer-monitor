# Printer fleet simulator (test fixture)

A tool for **verifying** printer-monitor without real devices.
It is NOT a product feature - do not extend it with new mechanisms.

## What it simulates

| Element | Protocol | Port | File |
|---|---|---|---|
| Toners, counters, model/name/location | SNMP v2c | 161/udp | `snmp_agent.py` |
| Device pages (web scraping / Selenium) | HTTP | 80 | `web_mock.py` |
| States (rotation) | - | - | `rotate.py` + `state.json` |

Each printer = a separate SNMP agent thread + a separate HTTP server,
bound to its own IP alias (`ip-aliases.sh` requires `CAP_NET_ADMIN`).
The state is re-read on every request - rotation works without restarts.

## Start (prnt-mon container)

```bash
# 1. IP aliases (ip-aliases.sh runs at container startup)
sh /workspace/simulator/ip-aliases.sh

# 2. printer list -> printers.csv / printers_counters.csv
python simulator/rotate.py write-csv

# 3. agents (background; -B = no .pyc cache - important with bind mounts)
nohup python -B simulator/snmp_agent.py > /tmp/snmp.log 2>&1 &
nohup python -B simulator/web_mock.py > /tmp/web.log 2>&1 &

# 4. verification
python main.py --check-toner            # toner/counter status
python main.py --report-counters        # counter report (no e-mail)
python dashboard.py                     # dashboard on :5001
```

## State rotation (hot-reload)

```bash
python simulator/rotate.py list
python simulator/rotate.py offline 172.21.0.11 true     # printer does not respond
python simulator/rotate.py toner  172.21.0.15 "Toner Black" --level 3
python simulator/rotate.py toner  172.21.0.19 "Toner Black" --current -3
python simulator/rotate.py counters 172.21.0.12 5000 8000
python simulator/rotate.py reset                        # back to seed
```

## Verification scenarios

| Scenario | Commands | Expected effect in main.py/dashboard |
|---|---|---|
| Low alert (threshold 20%) | `toner ... --level 18` | LOW alert + log entry |
| Critical alert (threshold 5%) | `toner ... --level 3` | CRITICAL alert + high-priority e-mail |
| 3-day cooldown (W10) | alert -> change to 80% -> alert again | 2nd alert NOT sent (timestamp in DB) |
| Printer offline | `offline IP true` | SNMP timeout -> 'PRINTER OFFLINE (TIMEOUT)' |
| HISTORY fallback | offline with no DB data | HISTORY entry in the counter report |
| Special value -3 | `toner ... --current -3` | status 'low', level = toner_low_status_percent |
| New toner (max -2) | `toner ... --current 0 --max -2` (seed) | status 'new', 100% |
| Consumable exclusions | Waste/Drum/Developer in seed | not shown on the dashboard |

## Notes

- `state.json` is gitignored (local rotation data).
- IPs 172.21.0.11-22 = the docker `prnt-mon` network subnet (172.21.0.0/16).
- After `docker restart prnt-mon`, `start-services.sh` restarts everything
  automatically (IP aliases + agents + gunicorn).
- Per-printer custom OIDs are tested via `[CUSTOM_OIDS:IP]` sections in config.ini
  (also covered by the unit test `tests/test_core.py`).
