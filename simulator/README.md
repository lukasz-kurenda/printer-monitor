# Symulator floty drukarek (test fixture)

Narzędzie do **weryfikacji** printer-monitor bez realnych urządzeń.
Nie jest funkcją produktu — nie rozbudowuj o nowe mechanizmy.

## Co symuluje

| Element | Protokół | Port | Plik |
|---|---|---|---|
| Tonery, liczniki, model/nazwa/lokalizacja | SNMP v2c | 161/udp | `snmp_agent.py` |
| Strony urządzeń (web scraping / Selenium) | HTTP | 80 | `web_mock.py` |
| Stany (rotacja) | — | — | `rotate.py` + `state.json` |

Każda drukarka = osobny wątek agenta SNMP + osobny serwer HTTP,
bindowany na swoim aliasie IP (`ip-aliases.sh` wymaga `CAP_NET_ADMIN`).
Stan odczytywany świeżo przy każdym zapytaniu — rotacja działa bez restartu.

## Start (kontener prnt-mon)

```bash
# 1. aliasy IP (przy starcie kontenera robi to ip-aliases.sh)
sh /workspace/simulator/ip-aliases.sh

# 2. lista drukarek -> printers.csv / printers_counters.csv
python simulator/rotate.py write-csv

# 3. agenci (w tle; -B = bez cache .pyc - wazne przy bind-mount)
nohup python -B simulator/snmp_agent.py > /tmp/snmp.log 2>&1 &
nohup python -B simulator/web_mock.py > /tmp/web.log 2>&1 &

# 4. weryfikacja
python main.py --check-toner            # stan tonerow/licznikow
python main.py --report-counters        # raport licznikow (bez maila)
python dashboard.py                     # dashboard na :5001
```

## Rotacja stanów (hot-reload)

```bash
python simulator/rotate.py list
python simulator/rotate.py offline 172.21.0.11 true     # drukarka nie odpowiada
python simulator/rotate.py toner  172.21.0.15 "Toner Black" --level 3
python simulator/rotate.py toner  172.21.0.19 "Toner Black" --current -3
python simulator/rotate.py counters 172.21.0.12 5000 8000
python simulator/rotate.py reset                        # powrót do seed
```

## Scenariusze weryfikacyjne

| Scenariusz | Polecenia | Oczekiwany efekt w main.py/dashboardzie |
|---|---|---|
| Alert niski (prog 20%) | `toner … --level 18` | alert LOW + wpis w logu |
| Alert krytyczny (prog 5%) | `toner … --level 3` | alert CRITICAL + mail high priority |
| Cooldown 3 dni (W10) | alert → zmiana na 80% → alert ponownie | 2. alert NIE wysłany (timestamp w DB) |
| Drukarka offline | `offline IP true` | SNMP timeout → 'DRUKARKA OFFLINE (TIMEOUT)' |
| Fallback HISTORY | offline przy braku danych w DB | wpis HISTORY w raporcie liczników |
| Wartość specjalna -3 | `toner … --current -3` | status 'low', level = toner_low_status_percent |
| Toner nowy (max -2) | `toner … --current 0 --max -2` (seed) | status 'new', 100% |
| Wykluczenia materiałów | Waste/Drum/Developer w seed | nie pokazują się na dashboardzie |

## Uwagi

- `state.json` jest gitignorowany (dane lokalne rotacji).
- IP 172.21.0.11–22 = subnet sieci docker `prnt-mon` (172.21.0.0/16).
- Po `docker restart prnt-mon` uruchom ponownie `ip-aliases.sh` + agentów.
- Custom OID-y per drukarka testujesz przez sekcje `[CUSTOM_OIDS:IP]` w config.ini
  (pokryte też testem jednostkowym `tests/test_core.py`).
