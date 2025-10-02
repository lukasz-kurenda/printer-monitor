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
├── .gitignore          # Plik ignorujący niepotrzebne pliki w repozytorium
├── config.ini          # Główny plik konfiguracyjny (należy go utworzyć z config.ini.example)
├── dashboard.py        # Aplikacja webowa Flask (backend dashboardu)
├── encrypt_util.py     # Narzędzie do szyfrowania hasła SMTP
├── main.py             # Główny skrypt do zbierania danych
├── printers.csv        # Lista adresów IP drukarek do monitorowania tonerów
├── printers_counters.csv # Lista adresów IP drukarek do raportów liczników
├── printers.db         # Baza danych SQLite (tworzona automatycznie)
├── README.md           # Ta dokumentacja
└── templates/
    └── index.html      # Szablon HTML dla dashboardu
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

Aby uruchomić interfejs webowy, wykonaj polecenie:
```bash
python dashboard.py
```
Dashboard umożliwia:
*   Przeglądanie stanu tonerów wszystkich drukarek.
*   Ręczne uruchomienie skryptu sprawdzania tonerów (z wysyłką e-mail).
*   Ręczne wygenerowanie i wysłanie raportu liczników.

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
