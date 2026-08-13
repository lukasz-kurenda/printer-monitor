# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| main (1.1.x) | :white_check_mark: |

## Reporting a vulnerability

Please do NOT report vulnerabilities in public issues. Contact directly:

- GitHub Security Advisories: https://github.com/lukasz-kurenda/printer-monitor/security/advisories/new
- or open a private report via "Report a vulnerability" in the repository's Security tab.

## What should be reported

- Injections (HTML/SQL/OS) in reports or the dashboard
- Authentication/CSRF issues in the dashboard
- Device data leaks (names, locations, counters)
- Dependencies with known vulnerabilities (check: `pip-audit -r requirements.txt`)

## Policy

- Acknowledgment within 72h, status updates every 7 days.
- Details published after the fix is released.
