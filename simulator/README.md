# The simulator: your fleet, minus the printers

Testing should not depend on hardware. This little tool plays the part of a
small printer fleet — 12 fake devices that answer SNMP queries, serve web pages
for scraping, and let you break them in interesting ways. You can use it to try
the whole system, rehearse a demo, or simply understand how the monitoring works
before you plug in a single real printer.

It is a test helper, not a product feature — please don't extend it with new
mechanics.

## What it pretends to be

| Element | Protocol | Port | File |
|---|---|---|---|
| Toners, counters, model/name/location | SNMP v2c | 161/udp | `snmp_agent.py` |
| Device web pages (for Selenium scraping) | HTTP | 80 | `web_mock.py` |
| States (rotation) | — | — | `rotate.py` + `state.json` |

Every fake printer runs as its own SNMP agent thread plus its own HTTP server,
bound to its own IP alias (`ip-aliases.sh` requires `CAP_NET_ADMIN`). State is
re-read on every request, so you can rotate a toner level and see the result
immediately — no restarts, no waiting.

## Getting started (inside the prnt-mon container)

```bash
# 1. IP aliases (the container does this automatically on startup)
sh /workspace/simulator/ip-aliases.sh

# 2. point printers.csv at the fake fleet
python simulator/rotate.py write-csv

# 3. start the agents
nohup python -B simulator/snmp_agent.py > /tmp/snmp.log 2>&1 &
nohup python -B simulator/web_mock.py > /tmp/web.log 2>&1 &

# 4. verify as if they were real printers
python main.py --check-toner
python main.py --report-counters
```

## Playing with the fleet

```bash
python simulator/rotate.py list                                  # who is in the fleet
python simulator/rotate.py offline 172.21.0.11 true              # take a printer down
python simulator/rotate.py toner 172.21.0.15 "Toner Black" --level 3   # almost empty
python simulator/rotate.py toner 172.21.0.19 "Toner Black" --current -3  # special SNMP value
python simulator/rotate.py counters 172.21.0.12 5000 8000        # change the counters
python simulator/rotate.py reset                                 # back to the defaults
```

## Scenarios worth trying

| Scenario | Commands | What you should see |
|---|---|---|
| Low toner alert (threshold 20 %) | `toner ... --level 18` | LOW alert + log entry |
| Critical toner alert (threshold 5 %) | `toner ... --level 3` | CRITICAL alert + high-priority e-mail |
| Cooldown (3 days, W10) | alert → set 80 % → alert again | the 2nd alert is NOT sent (timestamp in DB) |
| Printer offline | `offline IP true` | SNMP timeout → "PRINTER OFFLINE (TIMEOUT)" |
| History fallback | offline with no DB data | HISTORY entry in the counter report |
| Special value -3 | `toner ... --current -3` | status 'low', level = toner_low_status_percent |
| New toner (max -2) | `toner ... --current 0 --max -2` (seed) | status 'new', 100 % |
| Excluded consumables | Waste/Drum/Developer in the seed | never shown on the dashboard |

## Notes

- `state.json` is gitignored (your local rotation data).
- IPs 172.21.0.11–22 belong to the docker `prnt-mon` network subnet (172.21.0.0/16).
- `write-csv` adds a `# TEST DATA - simulated fleet` header to printers.csv /
  printers_counters.csv (the loaders skip `#` lines) — the tracked templates stay empty.
- After `docker restart prnt-mon`, `start-services.sh` brings everything back
  automatically (aliases + agents + gunicorn).
- Per-printer custom OIDs can be tried through `[CUSTOM_OIDS:IP]` sections in
  config.ini (also covered by `tests/test_core.py`).
