# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| main (1.1.x) | ✅ |

## Reporting a vulnerability

Proszę NIE zgłaszać podatności w publicznych issue. Skontaktuj się bezpośrednio:

- GitHub Security Advisories: https://github.com/lukasz-kurenda/printer-monitor/security/advisories/new
- lub otwórz prywatny raport przez "Report a vulnerability" w zakładce Security repozytorium.

## Co podlega zgłoszeniu

- Wstrzyknięcia (HTML/SQL/OS) w raportach lub dashboardzie
- Problemy autoryzacji/CSRF w dashboardzie
- Wycieki danych urządzeń (nazwy, lokalizacje, liczniki)
- Zależności z znanymi podatnościami (sprawdzenie: `pip-audit -r requirements.txt`)

## Zasady

- Potwierdzenie zgłoszenia: 72h, status co 7 dni.
- Publikacja szczegółów po wydaniu poprawki.
