# Changelog

## [1.1.0] — 2026-08-12 — Audyt + utwardzenie (etapy /20–/55)

### Bezpieczeństwo (SEC)
- **SEC-K1**: usunięcie sekretów z historii gita (`git filter-repo`); aktywny `.gitignore`; `config.ini.example`; skan blobów = 0 trafień; force-push `0955c59`
- **SEC-K3**: dashboard z autoryzacją — login tokenem (`DASH_AUTH_TOKEN`/`[WWW] auth_token`), sesja signed cookie (HttpOnly, SameSite=Strict), CSRF na POST (403), fail-closed (503), `debug=False`, gunicorn, bind lokalny (`docker -p 127.0.0.1:5001:5001`)
- Audit: gitleaks 0 / bandit 0 / pip-audit 0 (raport: `reports/security/audit_20260812.md`)

### Poprawki (FIX)
- **FIX-K2**: scalenie zduplikowanej `get_counters_snmp` (custom OID-y + fallback total); TypeError przy drukarce offline nie przerywa już przebiegu
- Izolacja błędów per-drukarka (pętla nie umiera)
- Walidacja adresów IP w `printers*.csv`

### Ops (W5/W6/W8/W10)
- **W5**: `lockfile.py` — blokada PID + timestamp + wykrywanie stale-lock; koniec równoległych przebiegów (cron/dashboard), 409 na dashboardzie
- **W6**: `html.escape` w raportach e-mail
- **W8**: `snmp_timeout`/`snmp_retries`/`snmp_port` z configu (zamiast hardcode)
- **W10**: znacznik czasu alertu aktualizowany tylko po udanej wysyłce SMTP

### Wydajność i narzędzia
- Web scraping równoległy (`web_workers`, osobny Chromium na wątek): 12 drukarek 65s → 25s
- Rotacja logów: `RotatingFileHandler` (1 MB × 3) w `main.py` i `dashboard.py`
- Testy: 38 (rdzeń 21, dashboard 9, lockfile 8); CI GitHub Actions zielone

### Testowanie
- **INTEG-SIM**: symulator floty 12 fikcyjnych drukarek — SNMP agent (pysnmp 7, per-IP :161) + web mock (frameset, :80) + CLI rotacji stanów (`simulator/rotate.py`); weryfikacja e2e: alerty, liczniki, wykluczenia, offline, dashboard

## [1.0.0] — 2026-08-12 — Stan sprzed audytu (repozytorium przepisane)

- Pierwotna wersja aplikacji (historia oczyszczona z sekretów; commity sprzed `0955c59` niedostępne)
