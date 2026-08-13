# Printer Monitor

## Table of Contents

1.  [Quick start](#quick-start)
2.  [Project description](#project-description)
3.  [Main features](#main-features)
4.  [Project structure](#project-structure)
5.  [Installation and deployment](#installation-and-deployment)
6.  [Configuration](#configuration)
7.  [Usage](#usage)
8.  [Testing without printers (simulator)](#testing-without-printers-simulator)
9.  [Development environment (local)](#development-environment-local)
10. [VLAN access (administrators)](#vlan-access-administrators)
11. [Project status (roadmap)](#project-status-roadmap)
12. [Additional information](#additional-information)

---

## Quick start

Requirements: **Python 3.9+** (recommended 3.12), Chrome/Chromium (for web scraping of counters).

```bash
git clone https://github.com/lukasz-kurenda/printer-monitor.git
cd printer-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# configuration
cp config.ini.example config.ini        # fill in SMTP / recipients
python encrypt_util.py --generate-key   # encryption key for the SMTP password
python encrypt_util.py --encrypt        # encrypt the password -> paste into config.ini [SMTP] password

# printer list (one IP per line)
nano printers.csv

# first run (creates printers.db)
python main.py --check-toner

# dashboard
python dashboard.py                     # local: http://localhost:5001
# or production:  gunicorn -w 1 --bind 0.0.0.0:5001 dashboard:app
```

No printers at hand? Use the built-in 12-device simulator -
see [Testing without printers](#testing-without-printers-simulator).

Run tests: `python -m pytest`

## Project description

**Printer Monitor** is a comprehensive tool for managing and monitoring a fleet of
printers in a network environment. The application automatically collects toner level
and page counter data, presenting it in a clear web interface. Additionally, the system
sends e-mail notifications when consumables run low or reach critical levels, as well
as periodic counter reports.

The project was designed with flexibility and easy extensibility in mind.

## Main features

*   **Toner level monitoring**: Automatic polling of printers via **SNMP** for current
    consumable levels.
*   **Page counter reporting**: Collecting color and B&W page counts via **web scraping**
    (Selenium) and, if needed, via SNMP.
*   **E-mail notifications**: Alerts when toner drops below configured thresholds
    (low and critical), with a 3-day cooldown.
*   **Web dashboard**: Flask-based interface for visualizing the status of all monitored
    printers. Authentication: token (optional auto-login for local use), CSRF protected.
*   **Data history**: Readings stored in a local **SQLite** database, allowing historical
    tracking and continuity when a printer is temporarily unavailable.
*   **Security**: SMTP password encrypted with Fernet; secrets excluded from the repository
    (gitignore + history cleanup); sanitized HTML in e-mail reports.
*   **Flexible configuration**: `config.ini` (recipients, thresholds, custom per-IP OIDs).
*   **Test fleet simulator**: 12 fake printers (SNMP + HTTP) for testing without hardware.

## Project structure

```
.
├── .gitignore          # Ignores secrets, DB, logs, artifacts
├── config.ini          # Main configuration (local, gitignored; template: config.ini.example)
├── config.ini.example  # Configuration template (committed)
├── dashboard.py        # Flask web app (token auth + CSRF, optional auto-login)
├── encrypt_util.py     # SMTP password encryption utility (Fernet)
├── lockfile.py         # Run lock (PID + timestamp + stale detection)
├── main.py             # Main data collection script (SNMP + Selenium)
├── printers.csv        # Printer IPs for toner monitoring (test: simulator/rotate.py write-csv)
├── printers_counters.csv # Printer IPs for counter reports
├── printers.db         # SQLite database (created automatically)
├── requirements.txt    # Dependencies (floors/caps)
├── pytest.ini          # pytest configuration (pythonpath)
├── README.md           # This documentation
├── CHANGELOG.md        # Version history
├── SECURITY.md         # Security policy
├── reports/            # Reports: security audit, session digest, pip-audit
├── simulator/          # Printer fleet simulator (test fixture, see simulator/README.md)
├── tests/              # Unit tests (41): core, dashboard (auth/CSRF), lockfile
├── start-services.sh   # Container entrypoint - auto-starts all services
└── templates/
    ├── index.html      # Dashboard template (with CSRF meta + logout)
    └── login.html      # Token login page
```

## Installation and deployment

### Prerequisites

*   Python 3.9+ (recommended 3.12 - see dependency requirements: selenium >= 4.20)
*   Google Chrome or Chromium (required by Selenium)
*   Network access to monitored printers (port 161 for SNMP, port 80/443 for web scraping)

### Installation steps

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd printer-monitor
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure the application:**
    *   Copy `config.ini.example` to `config.ini`.
    *   Fill in all required fields (see [Configuration](#configuration)).

5.  **Generate the key and encrypt the password:**
    ```bash
    python encrypt_util.py --generate-key
    python encrypt_util.py --encrypt
    ```
    Paste the generated string as the `password` value in the `[SMTP]` section of `config.ini`.

6.  **Prepare printer lists:**
    *   `printers.csv` - IPs for toner monitoring.
    *   `printers_counters.csv` - IPs for counter reports.

7.  **Initialize the database:**
    ```bash
    python main.py --check-toner
    ```

8.  **Run the dashboard (optional):**
    ```bash
    python dashboard.py
    ```
    The dashboard will be available at `http://127.0.0.1:5001`.

## Configuration

### `config.ini`

*   **`[SMTP]`**: E-mail server settings (`server`, `port`, `user`, `sender_email`,
    `password` - encrypted with Fernet, `use_tls`).
*   **`[EMAILS]`**: Notification recipients (`recipient_email_toner_low`,
    `recipient_email_toner_critical`, `recipient_email_counters`, `recipient_email_errors`).
*   **`[MONITORING]`**: Thresholds (`toner_threshold_low`, `toner_threshold_critical`),
    `snmp_community`, `snmp_timeout`, `snmp_retries`, `snmp_port`, `web_workers`,
    keyword filters (`toner_filter_keywords`, `toner_exclude_keywords`).
*   **`[WWW]`**: `chrome_binary`, `headless`, `auth_token` (dashboard token),
    `auto_login` (local auto-login; keep `false` when exposed on a network).
*   **`[CUSTOM_OIDS:ip_address]`**: (Optional) per-IP custom OIDs for toners
    (`oid_desc`, `oid_max`, `oid_current`) and counters (`oid_color_count`, `oid_bw_count`).

### Finding custom OIDs

If standard reads fail (especially page counters), find model-specific OIDs with `snmpwalk`:

```bash
sudo apt-get install snmp
snmpwalk -v2c -c public <printer_ip> .1 > snmp_output.txt
```

Look for `count`, `counter`, `page`, `impression`, `black`, `color` keywords and copy
the numeric OID into `config.ini`.

### Printer list files

*   `printers.csv` / `printers_counters.csv`: one printer IP per line.

## Usage

### Command line

*   Check toners and counters (no e-mails): `python main.py --check-toner`
*   Force toner alerts: `python main.py --check-toner --force-toner-email`
*   Counter report (no e-mail): `python main.py --report-counters`
*   Force counter report e-mail: `python main.py --report-counters --force-counters-email`
*   Single printer test: `python main.py --check-toner -i 192.168.1.100`

### Web dashboard

The dashboard requires an auth token (SEC-K3). Set it in `[WWW] auth_token` in `config.ini`
or via the `DASH_AUTH_TOKEN` environment variable (env takes precedence):

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"   # generate a token
```

**Token-less mode (auto-login):** `[WWW] auto_login = true` (or env `DASH_AUTO_LOGIN=true`)
- authentication happens automatically, no token required. Allowed **only** for local
access (publish `-p 127.0.0.1:5001:5001`); CSRF on POST remains active in both modes.
In token mode the session lasts 30 days (token once every 30 days).

Production run (gunicorn + Docker, access via `http://localhost:5001`):

```bash
# inside the container (app binds 0.0.0.0 - exposure is limited by docker -p)
gunicorn -w 1 --bind 0.0.0.0:5001 dashboard:app

# on the host - publish ONLY on loopback (SEC-K3):
docker run -p 127.0.0.1:5001:5001 ...
```

Dev mode (no production server; still `debug=False`, local bind):
```bash
python dashboard.py   # listens on 127.0.0.1:5001
```

After logging in with the token the dashboard enables:
*   Browsing toner status of all printers.
*   Manually running the toner check (with e-mail alerts).
*   Manually generating and sending the counter report.

The session is permanent (30-day cookie) - enter the token once every 30 days,
not on every browser start.

Without a valid session all routes redirect to `/login`; POST requests without a CSRF
token (`X-CSRF-Token` header) are rejected (HTTP 403).

### Automation (Cron)

```cron
# Toners every 8 hours (00:05, 08:05, 16:05) with alerts
5 0,8,16 * * * /path/to/venv/bin/python /path/to/project/main.py --check-toner --force-toner-email >> /path/to/project/logs/cron.log 2>&1

# Counter report on the 1st of each month at 02:05
5 2 1 * * /path/to/venv/bin/python /path/to/project/main.py --report-counters --force-counters-email >> /path/to/project/logs/cron.log 2>&1
```

Use absolute paths. Alternatively use the helper scripts (`check_toners.sh`,
`report_counters.sh`, `run_task.sh`) which resolve paths relative to their own location
and fall back to the system `python3` when no `venv/` exists.

## Testing without printers (simulator)

The repository contains a simulator of a **fleet of 12 fake printers**
(SNMP agent + web mock) so the whole system can be tested without any hardware:
toners, alerts, counters, dashboard.

```bash
python simulator/rotate.py write-csv   # fill printers.csv with simulated printer addresses
python simulator/snmp_agent.py &       # SNMP agent (requires IP binding permissions, see simulator/README.md)
python simulator/web_mock.py &         # HTTP pages for web scraping
python main.py --check-toner           # normal verification against the simulator
python simulator/rotate.py list        # printer states
python simulator/rotate.py toner 172.21.0.15 "Toner Black" --level 3   # rotate a state
```

Details: `simulator/README.md`.

## Development environment (local)

Repository location on the host: `/opt/projects/printer-monitor`
(= `\\wsl.localhost\Ubuntu\opt\projects\printer-monitor`).

Working container `prnt-mon` (snapshot image `prnt-mon:dev`, network `prnt-mon`):

```bash
docker run -d --name prnt-mon --network prnt-mon --hostname prnt-mon \
  --cap-add NET_ADMIN --restart unless-stopped \
  -p 127.0.0.1:5001:5001 \        # local (auto-login)
  -p 0.0.0.0:5002:5002 \          # VLAN (token mode)
  -v /opt/projects/printer-monitor:/workspace \
  prnt-mon:dev \
  sh -c '[ -f /workspace/start-services.sh ] && sh /workspace/start-services.sh || sleep infinity'
```

**Auto-start:** the entrypoint runs `start-services.sh` (IP aliases -> regenerate empty
fleet -> SNMP agent + web mock + gunicorn). Thanks to `--restart unless-stopped` all
services come back automatically after a server/WSL/docker restart - no manual commands.

Manual service start (if stopped):

```bash
docker exec -d prnt-mon sh -c 'cd /workspace && nohup python -B simulator/snmp_agent.py > /tmp/snmp.log 2>&1 &'
docker exec -d prnt-mon sh -c 'cd /workspace && nohup python -B simulator/web_mock.py > /tmp/web.log 2>&1 &'
docker exec -d prnt-mon sh -c 'cd /workspace && nohup gunicorn -w 1 --bind 0.0.0.0:5001 dashboard:app > /tmp/gunicorn.log 2>&1 &'
```

- Local dashboard: `http://localhost:5001` - **auto-login** (no token; published only on 127.0.0.1)
- VLAN dashboard: `http://<machine-ip>:5002` - **token required** (`[WWW] auth_token`)
- Test fleet: `python simulator/rotate.py write-csv` + `rotate.py list|offline|toner|counters|reset`
- Tests: `python -m pytest` (requires installed dependencies + `pytest.ini`)
- Container rollback: image snapshots `prnt-mon:dev`, `prnt-mon:rollback-20260812`

## VLAN access (administrators)

The dashboard runs on a local machine (WSL2 + Docker) and administrators within a single
VLAN reach it via the machine IP (`192.168.1.80`).

**Required (secure mode for a network):**
- `[WWW] auto_login = false` - token mode mandatory (auto-login is local-only)
- token in `[WWW] auth_token` - shared between administrators (rotate on staff changes)
- CSRF on POST is active automatically

**Network mapping (WSL2 NAT -> VLAN):**

```bash
# 1. Docker publishes on all WSL interfaces:
#    docker run ... -p 0.0.0.0:5002:5002 ...

# 2. Windows - portproxy (requires ADMIN console):
netsh interface portproxy add v4tov4 listenport=5002 listenaddress=192.168.1.80 connectport=5002 connectaddress=127.0.0.1

# 3. Windows - firewall rule (ADMIN):
netsh advfirewall firewall add rule name="prnt-mon-dashboard" dir=in action=allow protocol=TCP localport=5002
```

Notes:
- `connectaddress=127.0.0.1` avoids the WSL2 IP change issue after restart
  (Windows loopback -> WSL localhostForwarding)
- Alternative without portproxy: `networkingMode=mirrored` in `%UserProfile%\.wslconfig`
  (WSL shares Windows interfaces) + `wsl --shutdown`
- Admin access: `http://192.168.1.80:5002` + token (port 5001 is local-only)
- Future recommendations (out of current scope): TLS via caddy/reverse proxy and
  per-administrator tokens

## Project status (roadmap)

**Completed scope (v1.1.x) - audit + hardening, no expansion:**
- FIX: duplicated `get_counters_snmp` merged (custom OIDs + fallback), per-printer error isolation
- SEC: git history purged of secrets, dashboard auth (token/CSRF/fail-closed), auto-login mode
- OPS: run lock (PID + stale detection), `html.escape` in reports, IP validation,
  SNMP timeouts from config, alert timestamp only after successful send, parallel web scraping,
  log rotation, service auto-start
- TEST: 12-device fleet simulator (SNMP + HTTP + state rotation), 41 tests, green CI

**Project decisions:**
- Target counter-read protocol: **SNMP** (web scraping remains as fallback)
- Dashboard: local `:5001` auto-login; VLAN administrators `:5002` token mode
- Simulator = test tool (not a product feature)

**Planned (out of current scope):** counter history charts on the dashboard, offline list,
`config.ini` wizard, IPv6, multiple SNMP communities, notification webhooks,
TLS via reverse proxy, per-administrator tokens.

Details: [CHANGELOG.md](CHANGELOG.md) - Security: [SECURITY.md](SECURITY.md)

## Additional information

*   **Author**: Lukasz Kurenda
