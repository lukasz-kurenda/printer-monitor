# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/) and this project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

- CI modernization (actions v5, Python 3.12) — pending the `workflow` scope on the push token.

## [1.1.1] — 2026-08-13 — Public-readiness + UX

### Added
- `SECURITY.md` with a vulnerability reporting process.
- README "Quick start" and simulator sections; project translated to English
  (code, UI, docs, reports).
- `AUTO_LOGIN` mode (`[WWW] auto_login` / `DASH_AUTO_LOGIN`) for local use;
  permanent 30-day sessions.
- Dashboard split: `:5001` local (auto-login, loopback only), `:5002` VLAN (token mode).
- `start-services.sh` — container entrypoint that brings every service back
  after a server restart (IP aliases, fleet, agents, gunicorn).
- CSRF healing for stale sessions (no more "Invalid CSRF token" after upgrades).

### Changed
- Cron scripts use relative paths instead of hardcoded `/home/admin/...`.
- Dashboard title/footer: "Printers Dashboard", GitHub icon link to the repository.
- Update interval text: every 2 hours (schedule marker in `check_toners.sh`).
- `printers.csv` / `printers_counters.csv` generated with a `# TEST DATA` header;
  seed data marked as test data.

### Removed
- `PLAN.md` (plan absorbed into README); dated reports (`session_digest.md`,
  `audit_20260812.md`).

### Security
- Removed all obsolete organisation references from the git history (filter-repo + force-push).

## [1.1.0] — 2026-08-12 — Audit + hardening

### Fixed
- Merged duplicated `get_counters_snmp` (custom OIDs + fallback) — an offline
  printer no longer aborts the whole run (FIX-K2).
- Per-printer error isolation; IP validation in `printers*.csv`.

### Added
- Run lock (`lockfile.py`, PID + timestamp + stale detection) — no more parallel
  runs from cron and the dashboard at the same time.
- `html.escape` in e-mail reports.
- SNMP timeouts/retries/port from config (no more hardcodes).
- Alert timestamp updated only after a successful SMTP send.
- Parallel web scraping (`web_workers`); log rotation (1 MB x 3).
- Test fleet simulator: 12 fake printers (SNMP + HTTP + state rotation).
- 41+ unit tests and green GitHub Actions CI.

### Security
- Secrets purged from the git history (`git filter-repo`, force-push `0955c59`).
- Dashboard authentication: token login, signed session cookie (HttpOnly,
  SameSite=Strict), CSRF on POST, fail-closed without a token, `debug=False`,
  gunicorn, loopback-only publish.
- Audit: gitleaks 0 / bandit 0 / pip-audit 0 (current dependency audit:
  `reports/pip_audit.json`).

## [1.0.0] — 2026-08-12 — Original version

- Original application (history rewritten; commits before `0955c59` are gone).
