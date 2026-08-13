# Printers Dashboard

> Keep an eye on every printer in your network — toner levels and page counters,
> collected automatically, with e-mail alerts when supplies run low.

![CI](https://github.com/lukasz-kurenda/printer-monitor/actions/workflows/python-app.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Tests](https://img.shields.io/badge/tests-43%20passed-green)
![pip-audit](https://img.shields.io/badge/pip--audit-0%20vulnerabilities-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## The short version

You know the feeling: someone walks in and asks "is there any toner left in the
printer by the conference room?" — and nobody knows. Printers Dashboard solves
this. It quietly polls your printers, shows the current toner levels on a simple
web page, tracks page counters over time, and sends you an e-mail when a toner
is about to run out (so you can order supplies before the printer stops, not after).

No accounts, no cloud, no subscriptions. It runs on your own machine and talks
to your printers directly.

## What it does

| What | How |
|---|---|
| Toner levels | SNMP polling of consumables (works with HP, Konica, Kyocera, Toshiba, Brother, Ricoh, Canon, Lexmark, OKI, Epson and friends) |
| Page counters | Color and B&W counts — via the printer's web interface (Selenium) or SNMP as a fallback |
| E-mail alerts | Low and critical toner warnings, plus a monthly counter report (Excel + HTML) |
| Dashboard | A clean web page showing the whole fleet at a glance |
| History | Readings stored in SQLite, so you can see trends — and the report still works when a printer is temporarily offline |
| Privacy | Your printers' data stays on your machine. The only outgoing traffic is to your SMTP server |

## Quick start

You need Python 3.9+ (3.12 recommended) and Chrome or Chromium installed.

```bash
git clone https://github.com/lukasz-kurenda/printer-monitor.git
cd printer-monitor

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 1. create your configuration
cp config.ini.example config.ini

# 2. protect your SMTP password (encrypted, not plain text)
python encrypt_util.py --generate-key
python encrypt_util.py --encrypt     # paste the result into config.ini

# 3. list your printers (one IP per line)
nano printers.csv

# 4. first run — creates the database and fetches everything
python main.py --check-toner
```

That's it. Your printers are now being watched.

No printers at hand? **Don't skip this repo just because you have no hardware** —
it ships with a simulator of 12 fake printers, so you can try everything right now:

```bash
python simulator/rotate.py write-csv   # fill printers.csv with fake IPs
python simulator/snmp_agent.py &       # SNMP server for the fake fleet
python simulator/web_mock.py &         # fake web pages for scraping
python main.py --check-toner           # run a normal check against the simulator
```

You can even simulate a printer running out of toner mid-demo:

```bash
python simulator/rotate.py toner 172.21.0.15 "Toner Black" --level 3
```

Details and all scenarios live in [`simulator/README.md`](simulator/README.md).

## The dashboard

```bash
gunicorn -w 1 --bind 0.0.0.0:5001 dashboard:app
```

Then open `http://localhost:5001`.

- **On your own machine** — you can enable auto-login and just look at it, no password prompt.
- **For your team on a VLAN** — token mode is mandatory, the dashboard is served on a
  separate port, and every action is CSRF-protected. Details in the
  [VLAN section](#for-your-team-on-a-vlan).

The page updates every 2 hours (that's a cron setting — see [Automation](#automation)).

## Configuration, explained

Everything lives in `config.ini`:

- **`[SMTP]`** — your mail server and the encrypted password (see Quick start).
- **`[EMAILS]`** — who gets low-toner alerts, critical alerts, and the monthly report.
  (They can be the same person or different teams — your call.)
- **`[MONITORING]`** — the thresholds that matter to you: when is toner "low"
  (default 20 %) and when is it "critical" (default 5 %). Also SNMP timeouts,
  community, and how many parallel scrapers to run.
- **`[WWW]`** — browser used for scraping, the dashboard token, and the local
  auto-login switch.
- **`[CUSTOM_OIDS:ip]`** — some printers hide their counters behind model-specific
  OIDs. If the defaults don't work for a device, point at the right OIDs per printer.
  The README's Configuration section shows how to find them with `snmpwalk`.

## Automation

Set it and forget it — add to your crontab (edit in `check_toners.sh`, marked `SCHEDULE`):

```cron
# toner check + alerts, every 2 hours
5 */2 * * * /path/to/printer-monitor/check_toners.sh

# monthly counter report, 1st of the month at 02:05
5 2 1 * * /path/to/printer-monitor/report_counters.sh
```

The scripts figure out their own paths and use your `venv` automatically.

## For your team on a VLAN

The dashboard runs on one machine; your administrators reach it over the VLAN
via the machine's IP (`192.168.1.80` in this example). Token mode is required on
the network — no auto-login out there:

```bat
:: as administrator on the Windows host
netsh interface portproxy add v4tov4 listenport=5002 listenaddress=192.168.1.80 connectport=5002 connectaddress=127.0.0.1
netsh advfirewall firewall add rule name="prnt-mon-dashboard" dir=in action=allow protocol=TCP localport=5002
```

- Administrators open `http://192.168.1.80:5002` and sign in with the token.
- Port 5001 stays local-only (auto-login for you).
- Rotate the token when people leave the team.

## Project structure — where things live

```
main.py              the worker: collects toners and counters, sends alerts
dashboard.py         the web dashboard
simulator/           fake printers for testing without hardware
db.py, printers.py, email_utils.py, alerts.py,
snmp_client.py, web_scraper.py, reports.py   cohesive modules behind the scenes
tests/               43 tests, run with `python -m pytest`
```

## Troubleshooting

| Symptom | Likely fix |
|---|---|
| No toner data for a printer | SNMP is blocked or the community name differs — check `[MONITORING] snmp_community` |
| Counters are empty but toners work | The web interface needs Chromium — install it, check `[WWW] chrome_binary` |
| "Invalid CSRF token" after an upgrade | Just refresh the page — old sessions are healed automatically |
| E-mail alerts are not sent | Run `python main.py --check-toner --force-toner-email` and read the log |
| Excel reports don't generate | `pip install pandas openpyxl` |
| Everything times out | Printer unreachable — `ping` it; timeouts are configurable in `[MONITORING]` |

Still stuck? Open an issue — we read them.

## Roadmap

Done in 1.1.x: security hardening (secrets removed from history, token + CSRF auth,
fail-closed behavior), a real run-lock, HTML-safe reports, parallel scraping,
log rotation, and the test simulator.

Ideas for the future (not yet built): history charts on the dashboard, an offline
printers list, a `config.ini` wizard, IPv6, multiple SNMP communities, webhook
notifications, TLS in front of the dashboard, per-administrator tokens.

## Security

See [SECURITY.md](SECURITY.md) — how to report a vulnerability, what we check,
and how to verify the dependencies yourself (`pip-audit -r requirements.txt`,
currently 0 known vulnerabilities).

## License

Released under the [MIT License](LICENSE) — free to use, modify and distribute.

---

Made by [Lukasz Kurenda](https://github.com/lukasz-kurenda). Feedback welcome.
