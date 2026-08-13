# Changelog

## [1.1.1] — 2026-08-13 — Public-readiness + UX

- **Public-readiness**: cron scripts use relative paths (instead of hardcoded `/home/admin/...`),
  `SECURITY.md`, README "Quick start" + simulator section, CI: `checkout@v5`/`setup-python@v5`/Python 3.12
  (reverted to remote state - token lacks `workflow` scope)
- **Sensitive references removed**: mentions of obsolete organisation / scan patterns removed from the entire git history
  (filter-repo), force-push
- **Authentication**: `AUTO_LOGIN` mode (`[WWW] auto_login` / `DASH_AUTO_LOGIN`) - automatic
  local login; permanent session (30 days); dashboard split: `:5001` local (auto-login,
  loopback only), `:5002` VLAN (token mode)
- **Ops**: `start-services.sh` as container entrypoint - full service auto-start after a
  server restart (IP aliases, fleet, SNMP agent, web mock, gunicorn)
- **Docs**: project plan moved to README ("Project status" section), `PLAN.md` removed,
  whole project translated to English

## [1.1.0] — 2026-08-12 — Audit + hardening (pipeline /20–/55)

### Security (SEC)
- **SEC-K1**: secrets removed from git history (`git filter-repo`); active `.gitignore`;
  `config.ini.example`; blob scan = 0 hits; force-push `0955c59`
- **SEC-K3**: dashboard with authentication - token login (`DASH_AUTH_TOKEN`/`[WWW] auth_token`),
  signed session cookie (HttpOnly, SameSite=Strict), CSRF on POST (403), fail-closed (503),
  `debug=False`, gunicorn, local bind (`docker -p 127.0.0.1:5001:5001`)
- Audit: gitleaks 0 / bandit 0 / pip-audit 0 (audit report 2026-08-12 archived in the pipeline log; current dependency audit: `reports/pip_audit.json`)

### Fixes (FIX)
- **FIX-K2**: merged duplicated `get_counters_snmp` (custom OIDs + fallback total);
  TypeError on an offline printer no longer aborts the run
- Per-printer error isolation (the loop no longer dies)
- IP validation in `printers*.csv`

### Ops (W5/W6/W8/W10)
- **W5**: `lockfile.py` - PID + timestamp lock with stale detection; no more parallel runs
  (cron/dashboard), HTTP 409 on the dashboard
- **W6**: `html.escape` in e-mail reports
- **W8**: `snmp_timeout`/`snmp_retries`/`snmp_port` from config (instead of hardcode)
- **W10**: alert timestamp updated only after a successful SMTP send

### Performance and tooling
- Parallel web scraping (`web_workers`, separate Chromium per thread): 12 printers 65s -> 25s
- Log rotation: `RotatingFileHandler` (1 MB x 3) in `main.py` and `dashboard.py`
- Tests: 41 (core 24, dashboard 9, lockfile 8); green GitHub Actions CI

### Testing
- **INTEG-SIM**: 12 fake printer fleet simulator - SNMP agent (pysnmp 7, per-IP :161)
  + web mock (frameset, :80) + state rotation CLI (`simulator/rotate.py`); e2e verification:
  alerts, counters, exclusions, offline, dashboard

## [1.0.0] — 2026-08-12 — State before the audit (history rewritten)

- Original application version (history cleaned of secrets; commits before `0955c59` unavailable)
