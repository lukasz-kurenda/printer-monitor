# Security Policy

This project takes security seriously: the repo history was scrubbed of secrets,
secrets never enter the repository, and the dashboard is protected with token
authentication and CSRF. This page explains what we check and how to report
a problem.

## Supported versions

| Version | Supported |
| ------- | --------- |
| main (1.1.x) | :white_check_mark: |

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Report privately:

- via GitHub Security Advisories:
  https://github.com/lukasz-kurenda/printer-monitor/security/advisories/new
- or use "Report a vulnerability" in the repository's Security tab.

You will get an acknowledgment within 72 hours and status updates every 7 days.
Details are published after a fix is released.

## What should be reported

- Injections (HTML / SQL / OS) in reports or the dashboard
- Authentication or CSRF issues in the dashboard
- Leaks of device data (names, locations, counters)
- Dependencies with known vulnerabilities

## What we check

- `pip-audit -r requirements.txt` — dependency vulnerabilities (currently 0 known)
- gitleaks + bandit in the security pipeline
- Secrets policy: `config.ini`, keys and databases are gitignored and never committed
