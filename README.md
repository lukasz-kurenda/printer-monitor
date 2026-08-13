# Monitor Drukarek

## Spis treści

1.  [Opis projektu](#opis-projektu)
2.  [Główne funkcjonalności](#główne-funkcjonalności)
3.  [Struktura projektu](#struktura-projektu)
4.  [Instalacja i wdrożenie](#instalacja-i-wdrożenie)
    *   [Wymagania wstępne](#wymagania-wstępne)
    *   [Kroki instalacji](#kroki-instalacji)
5.  [Konfiguracja](#konfiguracja)
    *   [Plik `config.ini`](#plik-configini)
    *   [Pliki z listą drukarek](#pliki-z-listą-drukarek)
6.  [Użytkowanie](#użytkowanie)
    *   [Uruchamianie z linii poleceń](#uruchamianie-z-linii-poleceń)
    *   [Dashboard webowy](#dashboard-webowy)
    *   [Automatyzacja (Cron)](#automatyzacja-cron)
7.  [Informacje dodatkowe](#informacje-dodatkowe)

---

## Opis projektu

**Monitor Drukarek** to kompleksowe narzędzie do zarządzania i monitorowania floty drukarek w środowisku sieciowym. Aplikacja automatycznie zbiera dane o poziomach tonerów oraz stanach liczników stron, prezentując je w czytelnym interfejsie webowym. Dodatkowo, system wysyła powiadomienia e-mail w przypadku niskiego lub krytycznego poziomu materiałów eksploatacyjnych oraz cykliczne raporty liczników.

Projekt został zaprojektowany z myślą o elastyczności i łatwej rozbudowie.

## Główne funkcjonalności

*   **Monitorowanie poziomów tonerów**: Automatyczne odpytywanie drukarek przez protokół **SNMP** w celu uzyskania informacji o aktualnych poziomach materiałów eksploatacyjnych.
*   **Raportowanie liczników stron**: Zbieranie danych o liczbie wydrukowanych stron (kolorowych i czarno-białych) za pomocą **web scrapingu** (Selenium) oraz, w razie potrzeby, za pomocą SNMP.
*   **Powiadomienia e-mail**: Wysyłanie alertów na skonfigurowane adresy e-mail, gdy poziom tonera spadnie poniżej określonego progu (niski i krytyczny).
*   **Dashboard webowy**: Przejrzysty interfejs użytkownika (oparty na Flask) do wizualizacji stanu wszystkich monitorowanych drukarek w czasie rzeczywistym.
*   **Historia danych**: Zapisywanie odczytów w lokalnej bazie danych **SQLite**, co pozwala na śledzenie historycznych stanów i zapewnia ciągłość danych w przypadku tymczasowej niedostępności drukarki.
*   **Bezpieczeństwo**: Szyfrowanie hasła do serwera SMTP przy użyciu dedykowanego narzędzia.
*   **Elastyczna konfiguracja**: Możliwość łatwego dostosowania ustawień (adresy e-mail, progi alertów, dane serwera SMTP, niestandardowe OIDy SNMP) za pomocą pliku `config.ini`.

## Struktura projektu

```
.
├── .gitignore          # Plik ignorujący sekrety, DB, logi, artefakty
├── config.ini          # Główny plik konfiguracyjny (lokalny, gitignored; wzorzec: config.ini.example)
├── config.ini.example  # Szablon konfiguracji (committed)
├── dashboard.py        # Aplikacja webowa Flask (auth token + CSRF, SEC-K3)
├── encrypt_util.py     # Narzędzie do szyfrowania hasła SMTP (Fernet)
├── lockfile.py         # Blokada uruchomień (PID + ts + stale-lock, W5)
├── main.py             # Główny skrypt do zbierania danych (SNMP + Selenium)
├── printers.csv        # Lista adresów IP drukarek do monitorowania tonerów (testowa: simulator/rotate.py write-csv)
├── printers_counters.csv # Lista adresów IP drukarek do raportów liczników
├── printers.db         # Baza danych SQLite (tworzona automatycznie)
├── requirements.txt    # Zależności (floors/caps)
├── pytest.ini          # Konfiguracja pytest (pythonpath)
├── README.md           # Ta dokumentacja
├── reports/            # Raporty: security audit, session digest, pip-audit
├── simulator/          # Symulator floty drukarek (test fixture, patrz simulator/README.md)
├── tests/              # Testy jednostkowe (38): rdzeń, dashboard (auth/CSRF), lockfile
└── templates/
    ├── index.html      # Szablon dashboardu (z CSRF meta + logout)
    └── login.html      # Strona logowania tokenem
```

## Instalacja i wdrożenie

### Wymagania wstępne

*   Python 3.8+
*   Przeglądarka Google Chrome lub Chromium (wymagana przez Selenium)
*   Dostęp sieciowy do monitorowanych drukarek (port 161 dla SNMP, port 80/443 dla web scrapingu)

### Kroki instalacji

1.  **Sklonuj repozytorium:**
    ```bash
    git clone <adres-repozytorium>
    cd printer-monitor
    ```

2.  **Utwórz i aktywuj środowisko wirtualne:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Zainstaluj zależności:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Skonfiguruj aplikację:**
    *   Skopiuj `config.ini.example` do `config.ini` (jeśli istnieje plik przykładowy) lub utwórz plik `config.ini` ręcznie.
    *   Wypełnij wszystkie wymagane pola w `config.ini` (patrz sekcja [Konfiguracja](#konfiguracja)).

5.  **Wygeneruj klucz i zaszyfruj hasło:**
    *   Wygeneruj plik `secret.key`, który będzie używany do szyfrowania.
        ```bash
        python encrypt_util.py --generate-key
        ```
        **Ważne:** Przechowuj plik `secret.key` w bezpiecznym miejscu! Nie dodawaj go do repozytorium (jest już w `.gitignore`).
    *   Zaszyfruj swoje hasło do serwera SMTP:
        ```bash
        python encrypt_util.py --encrypt
        ```
    *   Skopiuj wygenerowany ciąg znaków i wklej go jako wartość `password` w sekcji `[SMTP]` pliku `config.ini`.

6.  **Przygotuj listy drukarek:**
    *   Wypełnij plik `printers.csv` adresami IP drukarek, których tonery chcesz monitorować.
    *   Wypełnij plik `printers_counters.csv` adresami IP drukarek, dla których chcesz generować raporty liczników.

7.  **Zainicjuj bazę danych:**
    *   Uruchom skrypt po raz pierwszy, aby utworzyć i zainicjować bazę danych `printers.db`.
        ```bash
        python main.py --check-toner
        ```

8.  **Uruchom dashboard (opcjonalnie):**
    ```bash
    python dashboard.py
    ```
    Dashboard będzie dostępny pod adresem `http://0.0.0.0:5001`.

## Konfiguracja

### Plik `config.ini`

Plik `config.ini` jest podzielony na kilka sekcji:

*   **`[SMTP]`**: Ustawienia serwera e-mail.
    *   `server`, `port`, `user`, `sender_email`: Dane serwera SMTP.
    *   `password`: Zaszyfrowane hasło (wygenerowane przez `encrypt_util.py`).
    *   `use_tls`: `true` lub `false`, w zależności od wymagań serwera.

*   **`[EMAILS]`**: Adresy e-mail do powiadomień.
    *   `recipient_email_toner_low`: Adresaci alertów o niskim poziomie tonera.
    *   `recipient_email_toner_critical`: Adresaci alertów o krytycznym poziomie tonera.
    *   `recipient_email_counters`: Adresaci cyklicznych raportów liczników.

*   **`[MONITORING]`**: Główne ustawienia skryptu.
    *   `toner_threshold_low`, `toner_threshold_critical`: Progi procentowe dla alertów.
    *   `snmp_community`: Nazwa społeczności SNMP (zazwyczaj `public`).
    *   `toner_exclude_keywords`: Słowa kluczowe (oddzielone przecinkami), które powodują ignorowanie danego materiału (np. `waste,beben,developer`).

*   **`[WWW]`**: Ustawienia dla web scrapingu.
    *   `chrome_binary`: Ścieżka do pliku wykonywalnego przeglądarki Chrome/Chromium (np. `/usr/bin/chromium-browser`).
    *   `headless`: `true`, jeśli przeglądarka ma działać w tle.


*   **`[CUSTOM_OIDS:adres_ip]`**: (Opcjonalne) Definicja niestandardowych OID-ów SNMP dla konkretnej drukarki. Użyj tej sekcji, jeśli standardowe OIDy nie działają dla danego modelu. W tej sekcji można zdefiniować OID-y zarówno dla tonerów, jak i dla liczników stron.
    *   `oid_desc`, `oid_max`, `oid_current`: OID-y dla opisu, wartości maksymalnej i bieżącej tonerów.
    *   `oid_color_count`, `oid_bw_count`: OID-y dla liczników stron kolorowych i czarno-białych.

#### Jak znaleźć niestandardowe OID-y?

Jeśli domyślne metody odczytu danych zawodzą (szczególnie w przypadku liczników stron), konieczne może być znalezienie OID-ów specyficznych dla danego modelu drukarki. Można to zrobić za pomocą narzędzia `snmpwalk`.

1.  **Zainstaluj `snmpwalk`** (jest częścią pakietu `snmp` w większości dystrybucji Linux):
    ```bash
    sudo apt-get update && sudo apt-get install snmp
    ```

2.  **Przeskanuj całe drzewo MIB drukarki**, aby zapisać wszystkie dostępne OID-y do pliku:
    ```bash
    snmpwalk -v2c -c public <adres_ip_drukarki> .1 > snmp_output.txt
    ```
    (Zastąp `<adres_ip_drukarki>` adresem IP drukarki, a `public` nazwą społeczności SNMP, jeśli jest inna).

3.  **Przeanalizuj plik `snmp_output.txt`**: Szukaj w nim słów kluczowych, takich jak `count`, `counter`, `page`, `impression`, `black`, `color`. OID-y liczników często zawierają w opisie te słowa. Gdy znajdziesz obiecujące linie, skopiuj numeryczny OID i wklej go do odpowiedniego pola w `config.ini`.

    *Przykład:* Jeśli znajdziesz OID `.1.3.6.1.4.1.XXXX.XX.1.2.3` z opisem "Total Color Pages", wklej ten numer jako wartość `oid_color_count`.
=======
*   **`[CUSTOM_OIDS:adres_ip]`**: (Opcjonalne) Definicja niestandardowych OID-ów SNMP dla konkretnej drukarki. Użyj tej sekcji, jeśli standardowe OIDy nie działają dla danego modelu.

### Pliki z listą drukarek

*   **`printers.csv`**: Każdy wiersz powinien zawierać jeden adres IP drukarki, która ma być monitorowana pod kątem stanu tonerów i wyświetlana na dashboardzie.
*   **`printers_counters.csv`**: Każdy wiersz powinien zawierać jeden adres IP drukarki, która ma być uwzględniona w raporcie liczników.

## Użytkowanie

### Uruchamianie z linii poleceń

Skrypt `main.py` można uruchamiać z różnymi flagami:

*   **Sprawdzanie tonerów i liczników (bez wysyłania e-maili):**
    ```bash
    python main.py --check-toner
    ```
*   **Wymuszenie wysłania alertów e-mail o tonerach:**
    ```bash
    python main.py --check-toner --force-toner-email
    ```
*   **Generowanie raportu liczników (bez wysyłania e-maila):**
    ```bash
    python main.py --report-counters
    ```
*   **Wymuszenie wysłania raportu liczników e-mailem:**
    ```bash
    python main.py --report-counters --force-counters-email
    ```
*   **Testowanie pojedynczej drukarki:**
    ```bash
    python main.py --check-toner -i 192.168.1.100
    ```

### Dashboard webowy

Dashboard wymaga tokenu autoryzacji (SEC-K3). Ustaw go w `[WWW] auth_token` w `config.ini`
lub w zmiennej środowiskowej `DASH_AUTH_TOKEN` (env ma pierwszeństwo):

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"   # wygeneruj token
```

**Tryb bez tokenu (auto-login):** `[WWW] auto_login = true` (lub env `DASH_AUTO_LOGIN=true`)
— autoryzacja odbywa się automatycznie, token nie jest wymagany. Dozwolone **tylko**
przy dostępie lokalnym (publikacja `-p 127.0.0.1:5001:5001`); CSRF na POST pozostaje
aktywny w obu trybach. Przy trybie tokenowym sesja trwa 30 dni (token raz na 30 dni).

Uruchomienie produkcyjne (gunicorn + Docker, dostęp przez `http://localhost:5001`):

```bash
# w kontenerze (app bindowany na 0.0.0.0 - ekspozycje ogranicza docker -p)
gunicorn -w 1 --bind 0.0.0.0:5001 dashboard:app

# na hoscie - publikacja TYLKO na loopbacku (SEC-K3):
docker run -p 127.0.0.1:5001:5001 ...
```

Tryb deweloperski (bez serwera produkcyjnego; nadal `debug=False`, bind lokalny):
```bash
python dashboard.py   # slucha na 127.0.0.1:5001
```

Po zalogowaniu tokenem dashboard umożliwia:
*   Przeglądanie stanu tonerów wszystkich drukarek.
*   Ręczne uruchomienie skryptu sprawdzania tonerów (z wysyłką e-mail).
*   Ręczne wygenerowanie i wysłanie raportu liczników.

Sesja logowania jest trwała (cookie 30 dni) — token podajesz raz na 30 dni,
nie przy każdym uruchomieniu przeglądarki.

Bez ważnej sesji wszystkie ścieżki przekierowują na `/login`; zapytania POST bez
tokenu CSRF (nagłówek `X-CSRF-Token`) są odrzucane (HTTP 403).

### Automatyzacja (Cron)

Aby w pełni zautomatyzować monitorowanie, można dodać odpowiednie wpisy do `crontab`.

*   **Edycja crontab:**
    ```bash
    crontab -e
    ```
*   **Przykładowe wpisy:**
    ```cron
    # Sprawdzaj tonery co 8 godzin (o 00:05, 08:05, 16:05) i wysyłaj alerty
    5 0,8,16 * * * /sciezka/do/srodowiska/venv/bin/python /sciezka/do/projektu/main.py --check-toner --force-toner-email >> /sciezka/do/projektu/cron.log 2>&1

    # Generuj i wysyłaj raport liczników pierwszego dnia każdego miesiąca o 02:05
    5 2 1 * * /sciezka/do/srodowiska/venv/bin/python /sciezka/do/projektu/main.py --report-counters --force-counters-email >> /sciezka/do/projektu/cron.log 2>&1
    ```
    Pamiętaj, aby podać **pełne, bezwzględne ścieżki** do interpretera Python w środowisku wirtualnym oraz do skryptu `main.py`.

## Informacje dodatkowe

*   **Autor**: Łukasz Kurenda

## Środowisko deweloperskie (lokalne)

Repo na hoście: `/opt/projects/printer-monitor` (= `\\wsl.localhost\Ubuntu\opt\projects\printer-monitor`).

Kontener roboczy `prnt-mon` (obraz-snapshot `prnt-mon:dev`, sieć `prnt-mon`):

```bash
docker run -d --name prnt-mon --network prnt-mon --hostname prnt-mon \
  --cap-add NET_ADMIN --restart unless-stopped \
  -p 127.0.0.1:5001:5001 \
  -v /opt/projects/printer-monitor:/workspace \
  prnt-mon:dev \
  sh -c '[ -f /workspace/start-services.sh ] && sh /workspace/start-services.sh || sleep infinity'
```

**Auto-start:** entrypoint uruchamia `start-services.sh` (aliasy IP → regeneracja
pustej floty → agent SNMP + web mock + gunicorn). Dzięki `--restart unless-stopped`
wszystkie usługi wracają same po restarcie serwera/WSL/dockera — bez ręcznych poleceń.

Ręczny start usług (gdyby były wyłączone):

```bash
docker exec -d prnt-mon sh -c 'cd /workspace && nohup python -B simulator/snmp_agent.py > /tmp/snmp.log 2>&1 &'
docker exec -d prnt-mon sh -c 'cd /workspace && nohup python -B simulator/web_mock.py > /tmp/web.log 2>&1 &'
docker exec -d prnt-mon sh -c 'cd /workspace && nohup gunicorn -w 1 --bind 0.0.0.0:5001 dashboard:app > /tmp/gunicorn.log 2>&1 &'
```

- Dashboard: `http://localhost:5001` (token z `[WWW] auth_token` w `config.ini`)
- Testowa flota: `python simulator/rotate.py write-csv` + `rotate.py list|offline|toner|counters|reset`
- Testy: `python -m pytest` (wymaga zainstalowanych zależności + `pytest.ini`)
- Rollback wersji kontenera: snapshoty obrazów `prnt-mon:dev`, `prnt-mon:rollback-20260812`
